/**
 * WMSOpnameScanModule — layar "Sesi Opname" (mesin tunggal K9, `backend/core/opname_engine.py`).
 *
 * 2026-11-02 (keputusan owner K9): SATU layar untuk kain, aksesoris, dan barang jadi.
 *   - Gudang → Stok & Akurasi → Opname Stok (prop `kind` kosong);
 *   - Portal Aksesoris → Stok Opname (prop `kind="aksesoris"`, menu terpisah, mesin sama).
 * Alur: pilih LOKASI (wajib; opsional zona/rak/bin, jenis, daftar barang) → hitung BUTA (qty sistem
 * tidak tampil; baris belum dihitung ≠ 0) → ajukan (konfirmasi "anggap 0") → supervisor melihat
 * selisih (hitung − stok sistem saat dihitung, tanpa kunci) → approve: saldo ditimpa, penempatan
 * bin diperbarui, satu jurnal per sesi. Scan memakai scanner bersama (wedge + kamera kontinu).
 *
 * Standar UI/UX v2 (8 Nov 2026): daftar sesi = PageLayout + tabel + unduh, form sesi baru = FormPopup pendek (dulu panel
 * di atas daftar), status = StatusBadge, kartu = StatTile, konfirmasi tolak = confirmDialog (dulu window.prompt),
 * arsip mesin lama tidak lagi menampilkan JSON mentah. Layar kerja hitung tetap di halaman (pemindai & kamera, HP).
 *
 * 10 Nov 2026 (owner: "harus jelas mau pilih all gudang, atau hanya zona atau rak … bisa pilih beberapa rak"):
 * form sesi baru mengikuti TINGKATAN. Langkah 1 = gudang (lokasi teratas saja; zona anaknya tidak lagi tampil
 * sebagai lokasi sendiri). Langkah 2 = cakupan: Seluruh gudang · Zona tertentu · Rak tertentu · Bin tertentu.
 * Zona/rak/bin dicentang (boleh banyak), dikelompokkan per induknya (rak per zona, bin per rak), dengan cari.
 * Zona anak gudang = hitung stok + penempatan; rak/bin = penempatan saja (mesin `sub_ids`, `with_areas`).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { IconButton } from './IconButton';
import { Notice, EmptyState, StatTile, StatusBadge } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { BarisDetail } from '@/components/ui/detail-popup';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateTimeID } from '@/lib/format';
import {
  ScanLine, Plus, X, ClipboardList, MapPin, AlertTriangle, PackageCheck, ArrowLeft,
  RefreshCw, ShieldCheck, Boxes, Printer, EyeOff, Minus, Search,
} from 'lucide-react';
import useUomOptions from '@/hooks/useUomOptions';
import { UomConversionHint, baseUnitOf } from './uom/UomPicker';
import UniversalScanner from './scanner/UniversalScanner';
import { toScanResult } from './scanner/ScanResult';
import { scanFeedback } from './scanner/scanCode';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmtNum = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('id-ID', { maximumFractionDigits: 4 }));
const fmtRp = (v) => 'Rp ' + Math.round(v || 0).toLocaleString('id-ID');
const STATUS_BADGE = {
  counting: { tone: 'primary' }, submitted: { tone: 'warning' }, approving: { tone: 'warning' },
  approved: { tone: 'success' }, rejected: { tone: 'danger' }, cancelled: { tone: 'muted' },
};
const STATUS_LABEL = {
  counting: 'Menghitung', submitted: 'Menunggu persetujuan', approving: 'Diproses', approved: 'Disetujui',
  rejected: 'Ditolak', cancelled: 'Dibatalkan', open: 'Aktif (lama)', pending_approval: 'Menunggu (lama)',
};
const KIND_OPTS = [['bahan', 'Kain / bahan'], ['aksesoris', 'Aksesoris'], ['fg', 'Barang jadi']];
const LINE_STATUS = {
  belum: ['Belum dihitung', 'muted'],
  dihitung: ['Dihitung', 'success'],
  nol: ['Anggap 0', 'warning'],
};
// Cakupan sesi, dari tingkat teratas ke bawah (gudang → zona → rak → bin).
const CAKUPAN = [['semua', 'Seluruh gudang'], ['zona', 'Zona tertentu'], ['rak', 'Rak tertentu'], ['bin', 'Bin tertentu']];
const KATA_CAKUPAN = { zona: 'zona', rak: 'rak', bin: 'bin' };

/**
 * Daftar centang berkelompok (boleh pilih banyak) untuk zona/rak/bin di form sesi baru.
 * grup = [{ kunci, label, item: [{ id, label, ket, nonaktif, alasan }] }]. Kotak cari muncul bila pilihannya banyak.
 */
function DaftarCentang({ grup, terpilih, onUbah, testId }) {
  const [cari, setCari] = useState('');
  const semuaItem = grup.flatMap((g) => g.item);
  const q = cari.trim().toLowerCase();
  const tampil = grup
    .map((g) => ({ ...g, item: q ? g.item.filter((i) => `${i.label} ${i.ket || ''} ${g.label || ''}`.toLowerCase().includes(q)) : g.item }))
    .filter((g) => g.item.length);
  const dipilih = new Set(terpilih);
  const ubahSatu = (id, on) => onUbah(on ? [...terpilih.filter((x) => x !== id), id] : terpilih.filter((x) => x !== id));
  const ubahGrup = (ids, on) => onUbah(on ? [...terpilih, ...ids.filter((x) => !dipilih.has(x))] : terpilih.filter((x) => !ids.includes(x)));
  return (
    <div className="space-y-2" data-testid={testId}>
      {semuaItem.length > 8 && (
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <GlassInput value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari kode atau nama"
            aria-label="Cari pilihan" className="pl-9" data-testid={`${testId}-cari`} />
        </div>
      )}
      <div className="max-h-72 divide-y divide-[var(--glass-border)] overflow-y-auto rounded-md border border-[var(--glass-border)]">
        {tampil.length === 0 ? (
          <EmptyState icon={Search} title="Tidak cocok" description="Ubah kata pencarian." className="py-6" testId={`${testId}-kosong`} />
        ) : tampil.map((g) => {
          const bisa = g.item.filter((i) => !i.nonaktif).map((i) => i.id);
          const penuh = bisa.length > 0 && bisa.every((id) => dipilih.has(id));
          return (
            <div key={g.kunci} role="group" aria-label={g.label || 'Pilihan'} className="space-y-1.5 px-3 py-2">
              {(g.label || bisa.length > 1) && (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs font-medium text-muted-foreground">{g.label || 'Semua pilihan'}</p>
                  {bisa.length > 1 && (
                    <Button type="button" variant="link" size="sm" onClick={() => ubahGrup(bisa, !penuh)}
                      data-testid={`${testId}-grup-${g.kunci}`}>{penuh ? 'Lepas semua' : `Pilih semua (${bisa.length})`}</Button>
                  )}
                </div>
              )}
              <div className="grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-2">
                {g.item.map((i) => (
                  <label key={i.id} htmlFor={`${testId}-${i.id}`}
                    className={`flex items-start gap-2 text-sm text-foreground ${i.nonaktif ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}>
                    <Checkbox id={`${testId}-${i.id}`} className="mt-0.5" checked={dipilih.has(i.id)} disabled={i.nonaktif}
                      onCheckedChange={(c) => ubahSatu(i.id, c === true)} data-testid={`${testId}-item-${i.id}`} />
                    <span className="min-w-0">
                      {i.label}
                      {(i.ket || i.alasan) && <span className="block text-xs text-muted-foreground">{i.alasan || i.ket}</span>}
                    </span>
                  </label>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function WMSOpnameScanModule({ token, kind = '' }) {
  const [sessions, setSessions] = useState([]);
  const [locations, setLocations] = useState([]);
  const [view, setView] = useState(null);          // {session, lines, totals, blind, archived, result}
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [zeroList, setZeroList] = useState(null);  // daftar baris belum dihitung saat submit

  // form sesi baru
  const [showNew, setShowNew] = useState(false);
  const [locId, setLocId] = useState('');           // gudang (lokasi teratas)
  const [cakupan, setCakupan] = useState('semua');  // semua | zona | rak | bin
  const [pilihan, setPilihan] = useState([]);       // id zona/rak/bin yang dicentang (boleh banyak)
  const [kinds, setKinds] = useState(kind ? [kind] : []);
  const [codes, setCodes] = useState('');
  // 2026-11-09: opname STOK AWAL — nilai stok dibukukan ke ekuitas saldo awal (disetujui Keuangan/owner)
  const [opening, setOpening] = useState(false);
  const [problems, setProblems] = useState(null);   // daftar baris yang menolak approve stok awal

  // hitung
  const [ctxBin, setCtxBin] = useState({ id: '', label: '' });   // '' = lantai / belum dirak
  const [mode, setMode] = useState('add');                          // add = +qty per scan, set = ketik jumlah
  const [scanQty, setScanQty] = useState(1);
  const [scanUom, setScanUom] = useState('');
  const [lastScan, setLastScan] = useState(null);
  // 2026-11-06 (audit layar scan Gudang): hasil scan tampil TEPAT di bawah kotak scan (prop `result`
  // UniversalScanner), bukan di pesan atas halaman yang di HP berada di luar layar.
  const [itemResult, setItemResult] = useState(null);
  const [binResult, setBinResult] = useState(null);

  const authH = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const jsonH = useMemo(() => ({ ...authH, 'Content-Type': 'application/json' }), [authH]);
  const flash = (type, text) => { setMessage({ type, text }); setTimeout(() => setMessage(null), 5000); };
  const errText = (d, fb) => (typeof d?.detail === 'string' ? d.detail : d?.detail?.message || fb);
  const focusItem = () => setTimeout(() => document.querySelector('[data-testid="opname-item-input"] input')?.focus(), 40);
  // Hasil scan barang: berhasil → testid lama `opname-last-scan`; ditolak → `opname-scan-result`.
  const itemFail = (text, detail) => setItemResult({ ...toScanResult(text), detail, testId: 'opname-scan-result' });
  const binFail = (text) => setBinResult({ ...toScanResult(text), testId: 'opname-bin-result' });
  const resetScanUi = () => { setItemResult(null); setBinResult(null); };

  const loadSessions = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/wms/opname3/sessions${kind ? `?kind=${kind}` : ''}`, { headers: authH });
      if (r.ok) setSessions(await r.json());
    } catch (e) { console.error(e); }
  }, [authH, kind]);

  const loadLocations = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/wms/opname3/locations`, { headers: authH });
      if (r.ok) {
        // 2026-11-07 (Tahap 5): ruang KANTOR (Kantor Pusat, Ruang HR, …) tidak menyimpan stok — dulu ikut
        // tampil sebagai lokasi opname. Sama dengan aturan owner No.18(a): kantor tidak ikut pemilih lokasi stok.
        const rows = (await r.json()).filter((l) => l.type !== 'kantor');
        setLocations(rows);
      }
    } catch (e) { console.error(e); }
  }, [authH]);

  const loadDetail = useCallback(async (id) => {
    try {
      const r = await fetch(`${API}/api/wms/opname3/sessions/${id}`, { headers: authH });
      const d = await r.json();
      if (r.ok) { setView(d); return d; }
      flash('error', errText(d, 'Gagal memuat sesi'));
    } catch (e) { console.error(e); }
    return null;
  }, [authH]);

  useEffect(() => {
    (async () => { setLoading(true); await Promise.all([loadSessions(), loadLocations()]); setLoading(false); })();
  }, [loadSessions, loadLocations]);

  // ── Form sesi baru: gudang → cakupan → zona/rak/bin (centang banyak) ──
  // Langkah 1 hanya lokasi TERATAS (gudang). Zona anak (mis. Ruang Aksesoris) dipilih di langkah cakupan.
  const gudangList = useMemo(() => locations.filter((l) => l.top !== false), [locations]);
  const loc = locations.find((l) => l.id === locId);
  const areas = loc?.areas || [];
  const adaZonaAnak = areas.length > 0;
  const zonaStok = adaZonaAnak;   // zona anak = lokasi stok sendiri → hitung stok + penempatan
  const namaZona = (id) => (id === loc?.id ? 'Di luar zona' : areas.find((a) => a.id === id)?.name || '');
  const tersedia = {
    semua: !!loc, zona: !!loc && (adaZonaAnak || loc.zones.length > 0),
    rak: !!loc && loc.racks.length > 0, bin: !!loc && loc.bins.length > 0,
  };
  const grupPilihan = (() => {
    if (!loc) return [];
    const zonaRak = Object.fromEntries(loc.zones.map((z) => [z.id, z]));
    const namaGrupZona = (z) => (adaZonaAnak && z.area_id
      ? `${namaZona(z.area_id)} · ${z.code} ${z.name || ''}` : `Zona ${z.code} ${z.name || ''}`).trim();
    if (cakupan === 'zona' && adaZonaAnak) {
      return [{ kunci: 'zona', label: '', item: [
        { id: loc.id, label: `Di luar zona (${loc.name})`, ket: 'Barang yang tercatat langsung di gudang, di luar zona mana pun' },
        ...areas.map((a) => ({ id: a.id, label: a.name || a.code, ket: a.code, nonaktif: a.quarantine,
          alasan: a.quarantine ? 'Karantina — dikelola dokumen karantina' : '' })),
      ] }];
    }
    if (cakupan === 'zona') return [{ kunci: 'zona', label: '', item: loc.zones.map((z) => ({ id: z.id, label: z.code, ket: z.name })) }];
    if (cakupan === 'rak') {
      return loc.zones.map((z) => ({
        kunci: z.id, label: namaGrupZona(z),
        item: loc.racks.filter((r) => r.zone_id === z.id).map((r) => ({ id: r.id, label: r.code, ket: r.name !== r.code ? r.name : '' })),
      })).filter((g) => g.item.length);
    }
    if (cakupan === 'bin') {
      return loc.racks.map((r) => ({
        kunci: r.id, label: `Rak ${r.code}${zonaRak[r.zone_id] ? ` · ${namaGrupZona(zonaRak[r.zone_id])}` : ''}`,
        item: loc.bins.filter((b) => b.rack_id === r.id).map((b) => ({ id: b.id, label: b.barcode || b.label })),
      })).filter((g) => g.item.length);
    }
    return [];
  })();
  const labelPilihan = grupPilihan.flatMap((g) => g.item).filter((i) => pilihan.includes(i.id)).map((i) => i.label);
  const subType = cakupan === 'semua' ? '' : cakupan === 'zona' ? (zonaStok ? 'area' : 'zone') : cakupan === 'rak' ? 'rack' : 'bin';
  const hitungStok = cakupan === 'semua' || (cakupan === 'zona' && zonaStok);
  // 10 Nov 2026 (keputusan owner): area produksi (cutting/jahit/QC/packing) tidak ikut "Seluruh gudang" — server
  // menyaringnya juga (core/opname_engine `_is_production_area`); pilih lewat "Zona tertentu" bila mau dihitung.
  const areaProduksi = (a) => !!a.production;
  const zonaIkut = areas.filter((a) => !a.quarantine && !areaProduksi(a)).map((a) => a.name || a.code);
  const zonaKarantina = areas.filter((a) => a.quarantine).map((a) => a.name || a.code);
  const zonaProduksi = areas.filter((a) => !a.quarantine && areaProduksi(a)).map((a) => a.name || a.code);
  const efekCakupan = !loc ? 'Pilih gudang dulu.'
    : cakupan === 'semua'
      ? `Stok dan penempatan seluruh gudang dihitung ulang${zonaIkut.length ? `, termasuk zona ${zonaIkut.join(', ')}` : ''}.`
        + (zonaKarantina.length ? ` Zona karantina (${zonaKarantina.join(', ')}) tidak ikut.` : '')
        + (zonaProduksi.length ? ` Area produksi (${zonaProduksi.join(', ')}) tidak ikut — pilih lewat Zona tertentu bila mau dihitung.` : '')
      : hitungStok ? 'Stok dan penempatan zona yang dicentang dihitung ulang.'
        : 'Penempatan bin saja — stok dan jurnal tidak berubah. Untuk memperbaiki stok, pilih seluruh gudang atau zona.';

  const gantiGudang = (id) => { setLocId(id); setCakupan('semua'); setPilihan([]); };
  const gantiCakupan = (c) => {
    setCakupan(c); setPilihan([]);
    if (!(c === 'semua' || (c === 'zona' && zonaStok))) setOpening(false);
  };
  // Portal Aksesoris: bawaan = gudang induk lokasi aksesoris → zona aksesoris itu (dulu lokasinya langsung).
  const bukaBaru = () => {
    setCakupan('semua'); setPilihan([]); setCodes(''); setOpening(false);
    const pref = kind ? locations.find((l) => l.storage_role === kind && !l.quarantine) : null;
    if (pref) {
      const top = pref.top_id || pref.id;
      setLocId(top);
      if (top !== pref.id) { setCakupan('zona'); setPilihan([pref.id]); }
    }
    setShowNew(true);
  };

  const sess = view?.session;
  const sessLoc = locations.find((l) => l.id === sess?.location_id);
  const isRak = sess?.level === 'rak';
  const lantaiKode = sess?.floor_code || sess?.location_code;
  const ctxBins = useMemo(() => {
    if (!sessLoc) return [];
    const sub = sess?.sub_scope;
    const zonaSesi = sess?.zone_ids;
    const kunci = { zone: 'zone_id', rack: 'rack_id', bin: 'id' }[sub?.type];
    const ids = sub?.ids || (sub?.id ? [sub.id] : []);
    return sessLoc.bins.filter((b) => (!zonaSesi || zonaSesi.includes(b.zone_id)) && (!kunci || ids.includes(b[kunci])));
  }, [sessLoc, sess]);

  const lastMatId = lastScan?.material_id;
  const { options: uomOpts } = useUomOptions(lastMatId ? [lastMatId] : []);
  const scanUomOpt = lastMatId ? uomOpts[lastMatId] : null;
  const scanBaseUnit = baseUnitOf(scanUomOpt, '');
  // Pilihan satuan = sama dengan UomSelect (satuan master barang terakhir; bila belum ada, satuan dasarnya).
  const scanUnitBase = baseUnitOf(scanUomOpt, lastScan?.base_uom || '');
  const scanUnits = scanUomOpt?.units?.length ? scanUomOpt.units : (scanUnitBase ? [{ unit: scanUnitBase }] : []);
  const scanUnitValue = String(scanUom || scanBaseUnit || scanUnitBase || '');

  const printLocationLabel = async (id) => {
    try {
      const r = await fetch(`${API}/api/wms/locations/${id}/label-pdf`, { headers: authH });
      if (!r.ok) { const d = await r.json().catch(() => ({})); flash('error', errText(d, 'Gagal mencetak label')); return; }
      const url = URL.createObjectURL(await r.blob());
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { flash('error', e.message); }
  };

  const createSession = async () => {
    setBusy(true);
    try {
      // Gudang beserta zona anaknya (`with_areas`); zona/rak/bin yang dicentang dikirim sekaligus (`sub_scope_ids`).
      const body = {
        location_id: locId, with_areas: true, sub_scope_type: subType, sub_scope_ids: subType ? pilihan : [], kinds,
        material_codes: codes.split(/[\s,;]+/).map((c) => c.trim()).filter(Boolean), source: kind || 'gudang',
        opening: opening && hitungStok,
      };
      const r = await fetch(`${API}/api/wms/opname3/sessions`, { method: 'POST', headers: jsonH, body: JSON.stringify(body) });
      const d = await r.json();
      if (r.ok) {
        setShowNew(false); setCodes(''); setCakupan('semua'); setPilihan([]); setOpening(false);
        await loadSessions(); await loadDetail(d.id); setCtxBin({ id: '', label: '' }); setLastScan(null); resetScanUi();
        flash('success', `Sesi ${d.session_no} dibuat — ${d.scope_label} · ${d.lines} baris (${d.level === 'rak' ? 'penempatan saja' : 'stok dan penempatan'}).`);
      } else flash('error', errText(d, 'Gagal membuat sesi'));
    } catch (e) { flash('error', e.message); } finally { setBusy(false); }
  };

  const openSession = async (s) => { await loadDetail(s.id); setCtxBin({ id: '', label: '' }); setLastScan(null); resetScanUi(); };
  const backToList = async () => { setView(null); setZeroList(null); resetScanUi(); await loadSessions(); };

  const pickBin = async (raw) => {
    const code = (raw || '').trim(); if (!code) return;
    try {
      const qs = new URLSearchParams({ barcode: code, session_id: sess.id });
      const r = await fetch(`${API}/api/wms/opname3/resolve-bin?${qs}`, { headers: authH });
      const d = await r.json();
      if (!r.ok) { scanFeedback('error'); binFail(errText(d, `Kode "${code}" bukan bin/lokasi sesi ini`)); return; }
      scanFeedback('ok'); setBinResult(null); setCtxBin({ id: d.bin_id, label: d.label }); focusItem();
    } catch (e) { scanFeedback('error'); binFail(e.message); }
  };

  const post = async (path, payload) => {
    const r = await fetch(`${API}/api/wms/opname3/${path}`, { method: 'POST', headers: jsonH, body: JSON.stringify(payload) });
    const d = await r.json().catch(() => ({}));
    return [r, d];
  };

  const doScan = async (raw) => {
    const code = (raw || '').trim(); if (!code) return;
    if (isRak && !ctxBin.id) { scanFeedback('error'); itemFail('Pilih bin dulu', 'Hitung rak: pilih atau scan bin di bagian Lokasi hitung.'); return; }
    const q = Number(scanQty) > 0 ? Number(scanQty) : (mode === 'set' ? 0 : 1);
    const payload = { session_id: sess.id, bin_id: ctxBin.id, qty: q };
    if (scanUom && scanUom !== scanBaseUnit) payload.input_uom = scanUom;
    try {
      const [r, d] = mode === 'set'
        ? await post('count', { ...payload, item_barcode: code })
        : await post('scan', { ...payload, item_barcode: code });
      if (r.ok) {
        scanFeedback('ok'); setLastScan(d);
        setItemResult({
          tone: 'ok', testId: 'opname-last-scan',
          title: `Tercatat: ${d.material_code} · ${fmtNum(d.counted_qty)} ${d.base_uom || ''}`.trim(),
          detail: `${d.material_name || ''} · ${d.bin_label || 'lantai / belum dirak'}`,
        });
        await loadDetail(sess.id);
      } else { scanFeedback('error'); itemFail(errText(d, 'Barang tidak dikenal'), `Kode: ${code}`); }
    } catch (e) { scanFeedback('error'); itemFail(e.message || 'Scan gagal terkirim', 'Periksa koneksi, lalu scan ulang.'); }
    focusItem();
  };

  const undoEntry = async (ln, ent) => {
    const [r, d] = await post('scan-undo', { session_id: sess.id, bin_id: ent.bin_id, item_material_id: ln.material_id, qty: 1 });
    if (r.ok) await loadDetail(sess.id); else flash('error', errText(d, 'Gagal mengurangi'));
  };

  const setLine = async (ln, patch) => {
    const [r, d] = await post('line', { session_id: sess.id, key: ln.key, ...patch });
    if (r.ok) await loadDetail(sess.id); else flash('error', errText(d, 'Gagal menyimpan baris'));
  };

  const doAction = async (action, extra = {}) => {
    let notes = '';
    if (action === 'reject') {
      const alasan = await confirmDialog({ title: `Tolak sesi ${sess.session_no}?`, confirmLabel: 'Tolak', danger: true,
        input: { label: 'Alasan penolakan' } });
      notes = typeof alasan === 'string' ? alasan : '';
      if (!notes) return;
    }
    setBusy(true);
    try {
      const [r, d] = await post(action, { session_id: sess.id, notes, ...extra });
      if (r.ok) {
        setZeroList(null); setProblems(null);
        if (action === 'approve') {
          const s = d.session?.summary || {};
          flash('success', `Opname disetujui. ${s.stock_writes || 0} baris stok ditimpa, ${s.positions_updated || 0} bin diperbarui`
            + (s.je_number ? `, jurnal ${s.je_number}.` : s.je_error ? `. Jurnal GAGAL: ${s.je_error}` : '.'));
        } else if (action === 'submit') flash('success', 'Diajukan. Selisih kini terlihat oleh supervisor.');
        else flash('success', `Sesi ${action === 'cancel' ? 'dibatalkan' : 'ditolak'}.`);
        await loadDetail(sess.id);
      } else if (r.status === 409 && d?.detail?.code === 'belum_dihitung') {
        setZeroList(d.detail.belum_dihitung || []);
      } else if (r.status === 409 && d?.detail?.code === 'opname_awal_ditolak') {
        setProblems(d.detail.problems || {}); flash('error', errText(d, 'Approve stok awal ditolak'));
      } else flash('error', errText(d, `Gagal ${{ submit: 'mengajukan', approve: 'menyetujui', reject: 'menolak', cancel: 'membatalkan' }[action] || 'memproses'} sesi`));
    } catch (e) { flash('error', e.message); } finally { setBusy(false); }
  };

  const cancelSession = async () => {
    const ok = await confirmDialog({
      title: `Batalkan sesi ${sess.session_no}?`,
      body: 'Hasil hitung sesi ini tidak dipakai dan stok tidak berubah.',
      confirmLabel: 'Batalkan sesi', cancelLabel: 'Kembali', danger: true,
    });
    if (ok) doAction('cancel');
  };

  // ── RENDER ─────────────────────────────────────────────────────────────
  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" /></div>;

  // Pesan atas halaman hanya untuk aksi sesi (buat, ajukan, setujui, tolak, batalkan); hasil scan ada di bawah kotak scan.
  const banner = message && (
    <Notice tone={message.type === 'success' ? 'success' : 'danger'} title={message.text} testId="opname-message" />
  );
  const lencana = (st, testId) => {
    const b = STATUS_BADGE[st] || { tone: 'muted' };
    return <StatusBadge status={st} label={STATUS_LABEL[st] || 'Lainnya'} tone={b.tone} testId={testId} />;
  };

  // ── DAFTAR ──
  if (!view) {
    const kolomSesi = [
      { kunci: 'no', label: 'No. sesi', hp: 'judul', isi: (s) => (
        <span className="inline-flex flex-wrap items-center gap-1.5 font-medium" data-testid={`opname-session-${s.session_no}`}>
          {s.session_no}
          {s.archived && <StatusBadge status="arsip" label="Arsip" tone="muted" />}
          {s.level === 'rak' && <StatusBadge status="rak" label="Rak" tone="muted" />}
          {s.mode === 'opening' && <StatusBadge status="stok-awal" label="Stok awal" tone="primary" />}
        </span>) },
      { kunci: 'cakupan', label: 'Cakupan', hp: 'keterangan', isi: (s) => <span className="text-sm">{s.scope_label || '—'}</span> },
      { kunci: 'dibuat', label: 'Dibuat', isi: (s) => <span className="text-sm md:whitespace-nowrap">{formatDateTimeID(s.created_at)}</span> },
      { kunci: 'jurnal', label: 'Jurnal', hp: false, isi: (s) => <span className="text-sm">{s.je_number || '—'}</span> },
      { kunci: 'status', label: 'Status', isi: (s) => lencana(s.status) },
    ];
    return (
      <PageLayout testId="wms-opname-scan-module" title={kind === 'aksesoris' ? 'Stok opname aksesoris' : 'Sesi opname'}
        subtitle="Hitung stok fisik per lokasi; transaksi tetap jalan dan selisih dibukukan setelah disetujui."
        actions={<Button onClick={bukaBaru} data-testid="opname-new-btn"><Plus /> Opname baru</Button>}
        tools={<>
          <TombolUnduh namaBerkas={kind === 'aksesoris' ? 'sesi-opname-aksesoris' : 'sesi-opname'} namaLembar="Sesi opname"
            baris={sessions} testId="opname-unduh" kolom={[
              { label: 'No. sesi', nilai: (s) => s.session_no },
              { label: 'Cakupan', nilai: (s) => s.scope_label || '' },
              { label: 'Level', nilai: (s) => (s.level === 'rak' ? 'Rak' : 'Lokasi') },
              { label: 'Dibuat', nilai: (s) => formatDateTimeID(s.created_at) },
              { label: 'Jurnal', nilai: (s) => s.je_number || '' },
              { label: 'Status', nilai: (s) => STATUS_LABEL[s.status] || '' },
              { label: 'Arsip', nilai: (s) => (s.archived ? 'Ya' : '') },
            ]} />
          <Button variant="outline" size="icon" onClick={loadSessions} title="Muat ulang" aria-label="Muat ulang" data-testid="opname-refresh">
            <RefreshCw />
          </Button>
        </>}
        summary={banner}>
        <TabelData kolom={kolomSesi} baris={sessions} kunci={(s) => s.id} onKlikBaris={openSession} testId="opname-sesi-tabel"
          kosong={<EmptyState icon={ClipboardList} title="Belum ada sesi opname" description="Klik Opname baru untuk mulai menghitung." testId="opname-empty" />} />

        <FormPopup open={showNew} onClose={() => setShowNew(false)} ukuran="panjang" judul="Sesi opname baru"
          keterangan="Pilih gudang, lalu seberapa luas yang dihitung. Jumlah sistem disembunyikan selama menghitung."
          onSimpan={createSession} menyimpan={busy} bisaSimpan={!!locId && (cakupan === 'semua' || pilihan.length > 0)}
          labelSimpan="Mulai hitung" testId="opname-new-panel">
          {/* 1 · Gudang: hanya tingkat teratas; zona di dalamnya dipilih di langkah 2. */}
          <Isian label="Gudang" wajib htmlFor="opname-location-field">
            <div className="flex gap-2">
              <div className="min-w-0 flex-1">
                <SmartNativeSelect id="opname-location-field" value={locId} onChange={(e) => gantiGudang(e.target.value)} className="w-full" data-testid="opname-location">
                  <option value="">Pilih gudang</option>
                  {gudangList.map((l) => <option key={l.id} value={l.id} disabled={l.quarantine}>{l.code} - {l.name}{l.quarantine ? ' (karantina — dikelola dokumen karantina)' : ''}</option>)}
                </SmartNativeSelect>
              </div>
              {locId && <IconButton label="Cetak label lokasi" onClick={() => printLocationLabel(locId)} data-testid="opname-print-location"><Printer className="w-4 h-4 text-muted-foreground" /></IconButton>}
            </div>
          </Isian>
          {/* 2 · Cakupan: dari tingkat teratas ke bawah. */}
          <Isian label="Yang dihitung" wajib petunjuk={efekCakupan}>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Yang dihitung" data-testid="opname-cakupan">
              {CAKUPAN.map(([k, label]) => (
                <Button key={k} type="button" size="sm" variant={cakupan === k ? 'default' : 'outline'} aria-pressed={cakupan === k}
                  disabled={!tersedia[k]} onClick={() => gantiCakupan(k)} data-testid={`opname-cakupan-${k}`}>{label}</Button>
              ))}
            </div>
          </Isian>
          {cakupan !== 'semua' && loc && (
            <Isian label={`Pilih ${KATA_CAKUPAN[cakupan]}`} wajib
              petunjuk={pilihan.length
                ? `${pilihan.length} ${KATA_CAKUPAN[cakupan]} dipilih: ${labelPilihan.slice(0, 8).join(', ')}${labelPilihan.length > 8 ? ', …' : ''}`
                : `Centang satu atau lebih ${KATA_CAKUPAN[cakupan]}.`}>
              <DaftarCentang key={`${locId}-${cakupan}`} grup={grupPilihan} terpilih={pilihan} onUbah={setPilihan}
                testId={`opname-pilih-${cakupan}`} />
            </Isian>
          )}
          <Isian label="Jenis barang" petunjuk="Tidak dicentang = semua jenis.">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              {KIND_OPTS.map(([k, label]) => (
                <label key={k} htmlFor={`opname-kind-${k}-cb`} className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
                  <Checkbox id={`opname-kind-${k}-cb`} checked={kinds.includes(k)} disabled={!!kind}
                    onCheckedChange={(c) => setKinds((v) => (c === true ? [...v, k] : v.filter((x) => x !== k)))} data-testid={`opname-kind-${k}`} />
                  {label}
                </label>
              ))}
            </div>
          </Isian>
          <Isian label="Jenis sesi" petunjuk={!hitungStok
            ? 'Opname stok awal hanya bila stok ikut dihitung: seluruh gudang, atau zona yang menyimpan stok sendiri.'
            : opening
              ? 'Stok awal: nilai hasil hitung dibukukan ke ekuitas saldo awal (bukan selisih persediaan), disetujui Keuangan/owner. Barang tanpa harga ditolak; sekali per barang × lokasi.'
              : 'Opname biasa: selisih dibukukan ke selisih persediaan.'}>
            <label htmlFor="opname-opening-cb" className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
              <Checkbox id="opname-opening-cb" checked={opening && hitungStok} disabled={!hitungStok}
                onCheckedChange={(c) => setOpening(c === true)} data-testid="opname-opening" />
              Opname stok awal (go-live)
            </label>
          </Isian>
          <Isian label="Hanya barang tertentu" htmlFor="opname-codes-field" petunjuk="Opsional — ketik atau scan kode, satu per baris. Kosongkan untuk menghitung semua barang.">
            <Textarea id="opname-codes-field" value={codes} onChange={(e) => setCodes(e.target.value)} rows={2} data-testid="opname-codes" />
          </Isian>
        </FormPopup>
      </PageLayout>
    );
  }

  // Layar kerja satu sesi (hitung / tinjau) tetap DI HALAMAN, bukan popup: pemindai & kamera butuh fokus terus-menerus
  // dan layar ini dipakai di HP sambil berjalan di gudang. Kepala tipis: tombol kembali + nomor sesi + status.
  const header = (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-3">
        <IconButton label="Kembali" onClick={backToList} data-testid="opname-back"><ArrowLeft className="w-4 h-4 text-muted-foreground" /></IconButton>
        <div className="min-w-0">
          <p className="text-base font-semibold tabular-nums text-foreground">{sess.session_no}</p>
          <p className="text-sm text-muted-foreground">{sess.scope_label || '-'}{view.archived ? ' · arsip baca-saja (mesin lama)' : ''}</p>
        </div>
      </div>
      {lencana(sess.status, 'opname-status')}
    </div>
  );

  // ── ARSIP (mesin lama) ──
  if (view.archived) {
    const rows = view.counts || view.session?.count_items || [];
    const ringkas = Object.entries(sess.summary || {}).filter(([, v]) => v === null || ['string', 'number', 'boolean'].includes(typeof v));
    return (
      <div className="space-y-4" data-testid="wms-opname-scan-module">
        {header}
        <GlassCard hover={false} className="space-y-3 p-4" data-testid="opname-archive">
          <p className="text-sm text-muted-foreground">Sesi ini dibuat mesin opname lama (sebelum mesin tunggal K9). Hanya bisa dibaca; untuk menghitung ulang buat sesi opname baru.</p>
          {ringkas.length > 0 && (
            <dl className="divide-y divide-[var(--glass-border)]">
              {ringkas.map(([k, v]) => (
                <BarisDetail key={k} label={k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())}>
                  {typeof v === 'number' ? fmtNum(v) : typeof v === 'boolean' ? (v ? 'Ya' : 'Tidak') : (v || '—')}
                </BarisDetail>
              ))}
            </dl>
          )}
          <div className="flex justify-end">
            <TombolUnduh namaBerkas={`opname-arsip-${sess.session_no}`} namaLembar="Arsip" baris={rows} testId="opname-archive-unduh"
              kolom={[
                { label: 'Kode', nilai: (c) => c.material_code },
                { label: 'Bin', nilai: (c) => c.bin_label || '' },
                { label: 'Hitung', nilai: (c) => Number(c.counted_qty || 0) },
                { label: 'Sistem', nilai: (c) => (c.system_qty !== undefined ? Number(c.system_qty || 0) : '') },
              ]} />
          </div>
          <TabelData baris={rows.map((c, i) => ({ ...c, _k: c.id || c.line_id || i }))} kunci={(c) => c._k} testId="opname-archive-tabel"
            kolom={[
              { kunci: 'kode', label: 'Kode', hp: 'judul', isi: (c) => c.material_code },
              { kunci: 'bin', label: 'Bin', isi: (c) => c.bin_label || '—' },
              { kunci: 'hitung', label: 'Hitung', rata: 'kanan', isi: (c) => <span className="tabular-nums">{fmtNum(c.counted_qty)}</span> },
              { kunci: 'sistem', label: 'Sistem', rata: 'kanan', isi: (c) => <span className="tabular-nums">{c.system_qty !== undefined ? fmtNum(c.system_qty) : '—'}</span> },
            ]} />
        </GlassCard>
      </div>
    );
  }

  const lines = view.lines || [];
  const totals = view.totals || {};
  const status = sess.status;
  const lineStatus = (st) => LINE_STATUS[st] || ['Lainnya', 'muted'];

  return (
    <div className="space-y-4" data-testid="wms-opname-scan-module">
      {header}
      {banner}

      {zeroList && (
        <Notice tone="warning" icon={AlertTriangle} testId="opname-zero-confirm" title={`${zeroList.length} baris belum dihitung`}>
          <p>Belum dihitung ≠ 0. Hitung dulu, atau konfirmasi bahwa barang ini memang tidak ada (stok menjadi 0 saat disetujui).</p>
          <div className="my-2 max-h-48 space-y-0.5 overflow-y-auto text-sm text-foreground">
            {zeroList.map((z) => <div key={z.key}>{z.material_code} — {z.material_name}{z.bin_label ? ` @ ${z.bin_label}` : ''}</div>)}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => doAction('submit', { confirm_zero: true })} disabled={busy} data-testid="opname-confirm-zero">Anggap 0 &amp; ajukan</Button>
            <Button onClick={() => setZeroList(null)} variant="outline">Kembali menghitung</Button>
          </div>
        </Notice>
      )}

      {status === 'counting' && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <GlassCard hover={false} className="space-y-4 p-4" data-testid="opname-count-panel">
            <p className="flex flex-wrap items-center gap-2 text-base font-semibold text-foreground"><ScanLine className="w-4 h-4 text-primary" /> Hitung <span className="flex items-center gap-1 text-xs font-normal text-muted-foreground"><EyeOff className="w-3 h-3" /> jumlah sistem disembunyikan</span></p>

            {/* 1 · Aksi utama: scan barang — paling atas, besar; hasil scan tepat di bawahnya. */}
            <div>
              <UniversalScanner variant="inline" onScan={doScan} continuous keepFocus autoFocus
                label="Scan barang" placeholder="Scan atau ketik kode barang, lalu Enter"
                inputClassName="h-12 text-base md:text-base" disabled={isRak && !ctxBin.id}
                result={isRak && !ctxBin.id
                  ? { tone: 'info', title: 'Pilih bin dulu', detail: 'Hitung rak: pilih atau scan bin di bagian Lokasi hitung di bawah.', testId: 'opname-scan-result' }
                  : itemResult}
                data-testid="opname-item-input" />
            </div>

            {/* 2 · Cara menghitung + jumlah & satuan */}
            <div className="space-y-2">
              <p className="text-sm font-medium text-muted-foreground">Cara menghitung</p>
              <div className="flex flex-wrap gap-2" role="group" aria-label="Cara menghitung">
                <Button type="button" variant={mode === 'add' ? 'default' : 'outline'} aria-pressed={mode === 'add'} onClick={() => setMode('add')} className="flex-1 basis-44" data-testid="opname-mode-add">Tambah tiap scan</Button>
                <Button type="button" variant={mode === 'set' ? 'default' : 'outline'} aria-pressed={mode === 'set'} onClick={() => setMode('set')} className="flex-1 basis-44" data-testid="opname-mode-set">Isi jumlah hitungan</Button>
              </div>
              <p className="text-xs text-muted-foreground" data-testid="opname-mode-help">
                {mode === 'set'
                  ? 'Isi jumlahnya, lalu scan barangnya — jumlah itu menjadi hasil hitung barang tersebut di lokasi ini.'
                  : 'Setiap scan menambah jumlah di bawah ke hitungan barang tersebut.'}
              </p>
              <div className="grid grid-cols-2 gap-2">
                <Isian label={mode === 'set' ? 'Jumlah hitungan' : 'Jumlah per scan'} htmlFor="opname-scan-qty-field" className="min-w-0">
                  <GlassInput id="opname-scan-qty-field" type="number" min={0} step="0.0001" value={scanQty}
                    onChange={(e) => setScanQty(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') focusItem(); }}
                    data-testid="opname-scan-qty" />
                </Isian>
                <Isian label="Satuan" className="min-w-0">
                  <SmartNativeSelect value={scanUnitValue} onChange={(e) => setScanUom(e.target.value)} disabled={scanUnits.length <= 1}
                    searchable={false} className="w-full" aria-label="Satuan" data-testid="opname-scan-uom"
                    title={scanUnits.length <= 1 ? 'Belum ada satuan lain — tambahkan kemasan di Master Material' : 'Pilih satuan hitung fisik'}>
                    {scanUnits.length
                      ? scanUnits.map((u) => <option key={u.unit} value={u.unit}>{u.unit}</option>)
                      : <option value="">Satuan barang</option>}
                  </SmartNativeSelect>
                </Isian>
              </div>
              <UomConversionHint opt={scanUomOpt} qty={scanQty} unit={scanUom || scanBaseUnit} fallbackUnit={lastScan?.base_uom || ''} testId="opname-scan-uom-hint" />
            </div>

            {/* 3 · Lokasi hitung: satu blok (pilih, atau scan label) */}
            <div className="space-y-2 border-t border-[var(--glass-border)] pt-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-1 text-sm font-medium text-muted-foreground"><MapPin className="w-3 h-3" /> Lokasi hitung{isRak ? ' (wajib pilih bin)' : ''}</span>
                <span className="min-w-0 truncate text-xs text-muted-foreground" data-testid="opname-active-bin">
                  Sekarang: <span className="font-medium text-foreground">{ctxBin.id ? ctxBin.label : `${lantaiKode} · lantai / belum dirak`}</span>
                </span>
              </div>
              <SmartNativeSelect value={ctxBin.id} onChange={(e) => { const b = ctxBins.find((x) => x.id === e.target.value); setCtxBin(b ? { id: b.id, label: b.label } : { id: '', label: '' }); setBinResult(null); focusItem(); }} className="w-full" aria-label="Lokasi hitung" data-testid="opname-bin-select">
                {!isRak && <option value="">Lantai / belum dirak ({lantaiKode})</option>}
                {isRak && <option value="">Pilih bin</option>}
                {ctxBins.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
              </SmartNativeSelect>
              <UniversalScanner variant="inline" onScan={pickBin} cameraButton={false} result={binResult}
                placeholder={isRak ? 'Atau scan label bin' : 'Atau scan label bin / lokasi'} data-testid="opname-bin-barcode" />
              <p className="text-xs text-muted-foreground">{isRak ? 'Hitung rak: pilih atau scan bin dulu sebelum scan barang.' : 'Tanpa bin berarti barang di lantai atau belum dirak.'}</p>
            </div>
          </GlassCard>

          <GlassCard hover={false} className="p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="flex items-center gap-2 text-base font-semibold text-foreground"><ClipboardList className="w-4 h-4 text-primary" /> Lembar hitung <span className="text-sm font-normal text-muted-foreground">{totals.counted || 0}/{totals.lines || 0} dihitung</span></p>
              <Button onClick={() => doAction('submit')} disabled={busy} size="sm" data-testid="opname-submit-btn"><PackageCheck className="w-4 h-4" /> Selesai &amp; ajukan</Button>
            </div>
            {/* Baris hitung = baris ringkas berisi kendali (kurangi per bin, rusak, resolusi) — tetap daftar padat untuk HP. */}
            <div className="max-h-[520px] divide-y divide-[var(--glass-border)] overflow-y-auto">
              {lines.length === 0 ? <EmptyState icon={ClipboardList} title="Tidak ada barang di stok saat mulai" description="Barang yang di-scan akan ditambahkan ke daftar ini." testId="opname-lines-empty" /> : lines.map((ln) => (
                <div key={ln.key} className="py-2" data-testid={`opname-line-${ln.material_code}`}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">{ln.material_code} <span className="font-normal text-muted-foreground">{ln.material_name}</span></p>
                      {ln.bin_label && <p className="text-xs text-muted-foreground">@ {ln.bin_label}</p>}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <StatusBadge status={ln.status} label={lineStatus(ln.status)[0]} tone={lineStatus(ln.status)[1]} />
                      {ln.status !== 'belum' && <span className="text-sm font-semibold tabular-nums text-foreground">{fmtNum(ln.counted_qty)} {ln.unit}</span>}
                    </div>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    {(ln.entries || []).map((e) => (
                      <span key={e.bin_id || 'lantai'} className="flex items-center gap-1 rounded border border-[var(--glass-border)] py-0.5 pl-1.5 text-xs text-muted-foreground">
                        {e.bin_label || 'lantai'}: {fmtNum(e.counted_qty)}
                        <Button type="button" variant="ghost" size="icon-sm" className="h-6 w-6" onClick={() => undoEntry(ln, e)}
                          title="Kurangi 1" aria-label="Kurangi 1" data-testid={`opname-undo-${ln.material_code}`}><Minus className="w-3 h-3" /></Button>
                      </span>
                    ))}
                    <label className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
                      <Checkbox checked={ln.reason === 'rusak'} onCheckedChange={(c) => setLine(ln, { reason: c === true ? 'rusak' : '' })}
                        data-testid={`opname-rusak-${ln.material_code}`} aria-label="Rusak" /> Rusak
                    </label>
                    {isRak && !ln.in_snapshot && (
                      <SmartNativeSelect value={ln.resolution || 'pindah'} onChange={(e) => setLine(ln, { resolution: e.target.value })} searchable={false}
                        className="h-8 w-full text-sm sm:w-auto" aria-label="Penyelesaian" data-testid={`opname-resolution-${ln.material_code}`}>
                        <option value="pindah">Pindah penempatan (stok tetap)</option>
                        <option value="lebih">Barang lebih (selisih lewat hitung penuh lokasi)</option>
                      </SmartNativeSelect>
                    )}
                  </div>
                </div>
              ))}
            </div>
            {/* Batalkan sesi dijauhkan dari "Selesai & ajukan" (dulu bersebelahan → mudah salah tekan) dan dikonfirmasi. */}
            <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-[var(--glass-border)] pt-3">
              <Button onClick={cancelSession} disabled={busy} variant="destructive" size="sm" data-testid="opname-cancel-btn">Batalkan sesi</Button>
              <span className="text-xs text-muted-foreground">Hanya bila sesi ini salah dibuat; hasil hitung tidak dipakai.</span>
            </div>
          </GlassCard>
        </div>
      )}

      {status !== 'counting' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Baris dihitung" value={`${totals.counted || 0}/${totals.lines || 0}`} sub="Baris terhitung dari seluruh baris sesi." />
            <StatTile label="Baris berselisih" value={fmtNum(totals.with_variance || 0)} sub="Hitung ≠ sistem saat dihitung." />
            <StatTile label="Nilai selisih" value={fmtRp(totals.total_variance_value)}
              accent={totals.total_variance_value < 0 ? 'danger' : totals.total_variance_value > 0 ? 'success' : 'default'}
              sub="Dinilai harga rata-rata saat mulai." />
            <StatTile label="Tanpa harga rata-rata" value={fmtNum(totals.uncosted || 0)} accent={totals.uncosted ? 'warning' : 'default'}
              sub="Baris ini tidak dijurnal." />
          </div>
          {isRak && <p className="text-sm text-muted-foreground">Hitung level rak hanya memperbaiki penempatan bin — stok dan jurnal tidak berubah.</p>}
          {sess.mode === 'opening' && (
            <Notice tone="info" testId="opname-opening-note" title="Opname stok awal">
              Nilai hasil hitung dibukukan ke akun persediaan lawan ekuitas saldo awal (bukan selisih persediaan). Yang boleh
              menyetujui hanya Keuangan/owner. Barang jadi tanpa harga rata-rata dinilai HPP standar; barang tanpa harga sama sekali
              ditolak.{sess.roll_import_no ? ` Berasal dari impor roll kain ${sess.roll_import_no} — roll aktif setelah disetujui.` : ''}
            </Notice>
          )}
          {problems && Object.keys(problems).length > 0 && (
            <Notice tone="danger" icon={AlertTriangle} testId="opname-opening-problems" title="Approve stok awal ditolak — perbaiki baris berikut">
              {Object.entries(problems).map(([k, rows]) => (
                <div key={k} className="mt-1">
                  <p className="font-medium">{{ tanpa_harga: 'Belum berharga', berkurang: 'Hitungan lebih kecil dari stok sistem',
                    sudah_ada_stok_awal: 'Sudah pernah dimuat stok awalnya', barang_klien: 'Barang milik klien maklon' }[k] || k}</p>
                  <ul className="ml-4 list-disc">
                    {rows.slice(0, 30).map((x, i) => <li key={i}>{x.material_code} {x.material_name ? `· ${x.material_name}` : ''} ({fmtNum(x.variance_qty)} {x.unit || ''})</li>)}
                  </ul>
                </div>
              ))}
            </Notice>
          )}

          {status === 'submitted' && (
            <div className="flex flex-wrap gap-2" data-testid="opname-approval-actions">
              <Button variant="success" onClick={() => doAction('approve')} disabled={busy} data-testid="opname-approve-btn"><ShieldCheck className="w-4 h-4" /> Setujui</Button>
              <Button variant="destructive" onClick={() => doAction('reject')} disabled={busy} data-testid="opname-reject-btn"><X className="w-4 h-4" /> Tolak</Button>
              <Button onClick={cancelSession} disabled={busy} variant="outline" data-testid="opname-cancel-btn">Batalkan sesi</Button>
            </div>
          )}
          {status === 'approved' && (
            <Notice tone="success" icon={PackageCheck} testId="opname-approved-banner"
              title={`Disetujui ${sess.approved_by_name || ''}`.trim()}>
              {sess.summary?.stock_writes || 0} baris stok ditimpa · {sess.summary?.positions_updated || 0} bin diperbarui
              {sess.je_number ? ` · jurnal ${sess.je_number}` : ''}{sess.summary?.je_error ? ` · jurnal GAGAL: ${sess.summary.je_error}` : ''}
            </Notice>
          )}

          <GlassCard hover={false} className="space-y-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="flex items-center gap-2 text-base font-semibold text-foreground"><Boxes className="w-4 h-4 text-primary" /> Selisih per baris</p>
              <TombolUnduh namaBerkas={`selisih-opname-${sess.session_no}`} namaLembar="Selisih" baris={lines} testId="opname-var-unduh"
                kolom={[
                  { label: 'Kode', nilai: (l) => l.material_code },
                  { label: 'Nama', nilai: (l) => l.material_name || '' },
                  ...(isRak ? [{ label: 'Bin', nilai: (l) => l.bin_label || '' }] : []),
                  { label: isRak ? 'Penempatan' : 'Stok saat mulai', nilai: (l) => Number(l.snapshot_qty || 0) },
                  ...(isRak ? [] : [
                    { label: 'Mutasi s/d dihitung', nilai: (l) => Number(l.mutation_qty || 0) },
                    { label: 'Sistem saat dihitung', nilai: (l) => Number(l.system_qty || 0) },
                  ]),
                  { label: 'Hitung', nilai: (l) => Number(l.counted_qty || 0) },
                  { label: 'Selisih', nilai: (l) => Number(l.variance_qty || 0) },
                  ...(isRak ? [] : [{ label: 'Nilai', nilai: (l) => Number(l.variance_value || 0) }]),
                  { label: 'Status', nilai: (l) => lineStatus(l.status)[0] },
                  { label: 'Rusak', nilai: (l) => (l.reason === 'rusak' ? 'Ya' : '') },
                ]} />
            </div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Kode</TableHead><TableHead>Nama</TableHead>{isRak && <TableHead>Bin</TableHead>}
                    <TableHead className="text-right">{isRak ? 'Penempatan' : 'Stok saat mulai'}</TableHead>{!isRak && <TableHead className="text-right">Mutasi s/d dihitung</TableHead>}{!isRak && <TableHead className="text-right">Sistem saat dihitung</TableHead>}
                    <TableHead className="text-right">Hitung</TableHead><TableHead className="text-right">Selisih</TableHead>{!isRak && <TableHead className="text-right">Nilai</TableHead>}<TableHead>Catatan</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {lines.map((l) => (
                    <TableRow key={l.key} data-testid={`opname-var-${l.material_code}`}>
                      <TableCell className="whitespace-nowrap font-medium">{l.material_code}</TableCell>
                      <TableCell className="text-muted-foreground">{l.material_name}</TableCell>
                      {isRak && <TableCell className="text-sm text-muted-foreground">{l.bin_label}</TableCell>}
                      <TableCell className="text-right tabular-nums">{fmtNum(l.snapshot_qty)}</TableCell>
                      {!isRak && <TableCell className="text-right tabular-nums text-muted-foreground">{fmtNum(l.mutation_qty)}</TableCell>}
                      {!isRak && <TableCell className="text-right tabular-nums">{fmtNum(l.system_qty)}</TableCell>}
                      <TableCell className="text-right tabular-nums">{fmtNum(l.counted_qty)}</TableCell>
                      <TableCell className={`text-right font-semibold tabular-nums ${l.variance_qty < 0 ? 'text-[hsl(var(--danger-text))]' : l.variance_qty > 0 ? 'text-[hsl(var(--success-text))]' : 'text-muted-foreground'}`}>{l.variance_qty > 0 ? '+' : ''}{fmtNum(l.variance_qty)}</TableCell>
                      {!isRak && <TableCell className="text-right tabular-nums text-muted-foreground">{fmtRp(l.variance_value)}</TableCell>}
                      <TableCell className="text-sm text-muted-foreground">
                        {lineStatus(l.status)[0]}{l.reason === 'rusak' ? ' · rusak (6-4300)' : ''}{isRak && !l.in_snapshot ? ` · ${l.resolution === 'lebih' ? 'barang lebih' : 'pindah penempatan'}` : ''}
                        {status === 'submitted' && !isRak && l.variance_qty < 0 && (
                          <label className="ml-2 inline-flex items-center gap-1.5">
                            <Checkbox checked={l.reason === 'rusak'} onCheckedChange={(c) => setLine(l, { reason: c === true ? 'rusak' : '' })} aria-label="Rusak" /> Rusak
                          </label>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </GlassCard>

          {(sess.summary?.findings || []).length > 0 && (
            <Notice tone="warning" icon={AlertTriangle} title="Temuan penempatan">
              {sess.summary.findings.map((f, i) => (
                <p key={i}>{f.jenis === 'barang_lebih' ? 'Barang lebih (belum masuk stok — hitung penuh lokasi)' : 'Bin sudah berisi barang lain (1 bin = 1 barang) — dianggap belum dirak'}: {lines.find((x) => x.material_id === f.material_id)?.material_code || f.material_id} × {fmtNum(f.qty)}</p>
              ))}
            </Notice>
          )}
        </div>
      )}
    </div>
  );
}

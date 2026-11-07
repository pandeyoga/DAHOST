/**
 * PurchaseReturnModule — Retur Pembelian (Portal Pengadaan). 2026-11-02, keputusan owner K11.
 *
 * Dokumen RTP-YYYYMM-NNNN milik Pengadaan: barang reject (Karantina) atau stok gudang dikembalikan
 * ke pemasok dengan pilihan penyelesaian — tukar barang, potong tagihan (nota debit), refund,
 * diterima dengan diskon, atau dimusnahkan. Harga = harga GR asal (GR WAJIB); selisih ke HPP
 * rata-rata → PPV. DA bukan PKP → tanpa PPN retur. Nota Debit & refund diselesaikan Keuangan
 * (layar Nota Debit). Backend: /api/rahaza/purchase-returns (routes/rahaza_purchase_returns.py).
 *
 * `PurchaseReturnCreateModal` dipakai juga oleh Karantina QC (tombol "Buat retur pembelian").
 * `StatusBadge` & `SETTLEMENT_OPTIONS` dipakai juga oleh Nota Debit (Portal Keuangan).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring pil, tabel + unduhan Excel/CSV, form = FormPopup,
 * detail = DetailPopup, tanggal kirim = DatePicker. Isian, aturan, dan API tidak berubah.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { PackageCheck, Plus, RefreshCw, Send, XCircle } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { toast } from 'sonner';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge as Lencana } from '../moduleAtoms';
import { apiGet, apiPost, fmtDate, fmtNum, fmtRp } from './procApi';

export const SETTLEMENT_OPTIONS = [
  { value: 'exchange', label: 'Tukar barang', hint: 'Barang dikirim balik; pemasok mengirim pengganti.' },
  { value: 'debit_note', label: 'Potong tagihan (nota debit)', hint: 'Barang dikirim balik; Keuangan menerbitkan nota debit — hutang/GRNI berkurang.' },
  { value: 'refund', label: 'Refund uang', hint: 'Barang dikirim balik; pemasok mentransfer uang. Hanya untuk barang yang sudah ditagih/bernilai.' },
  { value: 'accept_discount', label: 'Diterima dengan diskon', hint: 'Barang TIDAK dikirim balik; Keuangan mengetik harga diskon lewat nota debit.' },
  { value: 'destroy', label: 'Dimusnahkan', hint: 'Barang dimusnahkan; pilih siapa yang menanggung.' },
];
const STATUS_META = {
  draft: { label: 'Draf', tone: 'muted' },
  awaiting_settlement: { label: 'Menunggu penyelesaian', tone: 'warning' },
  settled: { label: 'Selesai', tone: 'success' },
  cancelled: { label: 'Batal', tone: 'muted' },
};
const SHIPPING = ['exchange', 'debit_note', 'refund', 'destroy'];
const settlementLabel = (v) => (SETTLEMENT_OPTIONS.find((o) => o.value === v) || {}).label || v;
const statusLabel = (s) => (STATUS_META[s] || STATUS_META.draft).label;
// Riwayat & jurnal dokumen dalam bahasa staf (kode dari routes/rahaza_purchase_returns.py)
const AKSI_RIWAYAT = {
  create: 'Dibuat', send: 'Dikirim', destroy: 'Dimusnahkan', receive_replacement: 'Pengganti diterima',
  refund: 'Refund dicatat', cancel: 'Dibatalkan', debit_note: 'Nota debit terbit',
};
const TAHAP_JURNAL = { send: 'Pengiriman', replacement: 'Penerimaan pengganti', refund: 'Refund', debit_note: 'Nota debit' };

export function StatusBadge({ status }) {
  const m = STATUS_META[status] || STATUS_META.draft;
  return <Lencana status={status} label={m.label} tone={m.tone} className={status === 'cancelled' ? 'line-through' : undefined} />;
}

/** Form buat Retur Pembelian — dari item karantina (`quarantineItem`) atau dari stok (pilih GR). */
export function PurchaseReturnCreateModal({ token, quarantineItem, onClose, onSaved }) {
  const fromQ = !!quarantineItem;
  const [settlement, setSettlement] = useState('debit_note');
  const [borne, setBorne] = useState('supplier');
  const [qty, setQty] = useState(fromQ ? quarantineItem.remaining_qty : '');
  const [reason, setReason] = useState('');
  const [notes, setNotes] = useState('');
  const [shipDate, setShipDate] = useState('');
  const [photos, setPhotos] = useState('');
  const [grs, setGrs] = useState([]);
  const [grId, setGrId] = useState('');
  const [lineId, setLineId] = useState('');
  // 2026-11-07 (Tahap 6 PG4): lokasi asal = HANYA lokasi yang memegang stok barang baris GR terpilih
  // (sumber sama dengan Transfer: /api/rahaza/material-stock). null = belum ada baris terpilih / sedang dimuat.
  const [stockLocs, setStockLocs] = useState(null);
  const [locId, setLocId] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const needGr = !fromQ || !['goods_receipt', 'grn_inspection'].includes(quarantineItem?.source?.type);
  const unvalued = fromQ ? Math.max(0, Number(quarantineItem.remaining_qty || 0) - Number(quarantineItem.valued_remaining_qty || 0)) : 0;

  useEffect(() => {
    if (!needGr) return;
    (async () => {
      try {
        const rows = await apiGet(token, '/api/wms/legacy/receiving');
        setGrs((Array.isArray(rows) ? rows : []).filter((g) => ['received', 'completed', 'partial_received', 'accepted'].includes(g.status)));
      } catch (e) { setErr(e.message); }
    })();
  }, [token, needGr, fromQ]);

  const gr = useMemo(() => grs.find((g) => g.id === grId), [grs, grId]);
  const grLines = useMemo(() => (gr?.items || []).filter((li) => li.material_id
    && (!fromQ || li.material_id === quarantineItem.material_id)), [gr, fromQ, quarantineItem]);
  const line = grLines.find((li) => (li.id || li.po_item_id) === lineId);
  const price = Number(line?.unit_price || line?.unit_cost || quarantineItem?.unit_cost || 0);
  const lineMaterialId = line?.material_id || '';

  useEffect(() => {
    setLocId('');
    if (fromQ || !lineMaterialId) { setStockLocs(null); return undefined; }
    let off = false;
    setStockLocs(null);
    apiGet(token, `/api/rahaza/material-stock?material_id=${encodeURIComponent(lineMaterialId)}`)
      .then((rows) => {
        if (off) return;
        // Tersedia = qty − dipesan (aturan server retur). Stok karantina QC tidak ikut: barang reject
        // diretur lewat item karantinanya (server menolak lokasi karantina sebagai asal stok).
        const byLoc = {};
        (Array.isArray(rows) ? rows : []).forEach((s) => {
          if (!s.location_id || s.quarantine || s.blocked) return;
          const cur = byLoc[s.location_id] || { id: s.location_id, code: s.location_code || '', name: s.location_name || '', qty: 0, unit: s.unit || '' };
          cur.qty += Number(s.qty || 0) - Number(s.reserved_quantity || 0);
          byLoc[s.location_id] = cur;
        });
        setStockLocs(Object.values(byLoc).filter((l) => l.qty > 1e-9)
          .sort((a, b) => String(a.code || a.name).localeCompare(String(b.code || b.name), 'id')));
      })
      .catch((e) => { if (!off) { setStockLocs([]); setErr(e.message); } });
    return () => { off = true; };
  }, [token, fromQ, lineMaterialId]);
  const stockAtLoc = (stockLocs || []).find((l) => l.id === locId);

  const submit = async () => {
    const q = parseFloat(qty);
    if (!(q > 0)) { setErr('Qty harus > 0'); return; }
    if (!reason.trim()) { setErr('Alasan retur wajib diisi'); return; }
    if (needGr && !grId) { setErr('GR asal wajib dipilih (harga & pemasok diambil dari penerimaan asal)'); return; }
    if (!fromQ && (!lineId || !locId)) { setErr('Pilih baris GR dan lokasi asal stok'); return; }
    if (!fromQ && stockAtLoc && q > stockAtLoc.qty + 1e-9) {
      setErr(`Stok barang ini di lokasi asal hanya ${fmtNum(stockAtLoc.qty)} ${stockAtLoc.unit || ''} — qty retur melebihi stok.`);
      return;
    }
    if (settlement === 'refund' && unvalued > 1e-6) {
      setErr('Refund hanya untuk barang yang sudah bernilai/ditagih. Barang yang ditolak saat penerimaan belum ditagih — pilih tukar barang atau potong tagihan.');
      return;
    }
    setBusy(true); setErr('');
    try {
      const body = {
        settlement, destroy_borne_by: settlement === 'destroy' ? borne : undefined,
        gr_id: needGr ? grId : undefined, reason, notes, ship_date: shipDate || undefined,
        photos: photos.split(/\s+/).filter(Boolean),
        lines: fromQ
          ? [{ quarantine_item_id: quarantineItem.id, qty: q, gr_item_id: lineId || undefined }]
          : [{ material_id: line.material_id, location_id: locId, qty: q, gr_item_id: lineId }],
      };
      const doc = await apiPost(token, '/api/rahaza/purchase-returns', body);
      toast.success(`Retur Pembelian ${doc.rtp_number} dibuat (draf)`);
      onSaved?.(doc);
    } catch (e) { setErr(e.message); setBusy(false); }
  };

  const ketKarantina = fromQ ? [
    `Karantina sisa ${fmtNum(quarantineItem.remaining_qty)} ${quarantineItem.unit}`,
    quarantineItem.source?.number, quarantineItem.source?.supplier_name,
    unvalued > 0 ? `${fmtNum(unvalued)} belum bernilai (ditolak saat GR, belum ditagih)` : null,
  ].filter(Boolean).join(' · ') : '';

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="rtp-create-modal"
      judul="Buat retur pembelian"
      keterangan={fromQ ? `${quarantineItem.material_code} · ${quarantineItem.material_name}` : 'Barang dari stok dikembalikan ke pemasok. Harga = harga GR asal; tanpa PPN.'}
      onSimpan={submit} menyimpan={busy} galat={err} labelSimpan="Buat retur (draf)">
      {fromQ && <p className="text-sm text-muted-foreground" data-testid="rtp-quarantine-info">{ketKarantina}</p>}
      <Isian label="Penyelesaian" wajib htmlFor="rtp-penyelesaian"
        petunjuk={(SETTLEMENT_OPTIONS.find((o) => o.value === settlement) || {}).hint}>
        <SmartNativeSelect id="rtp-penyelesaian" value={settlement} onChange={(e) => setSettlement(e.target.value)} data-testid="rtp-settlement">
          {SETTLEMENT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </SmartNativeSelect>
      </Isian>
      {settlement === 'destroy' && (
        <Isian label="Ditanggung" wajib htmlFor="rtp-ditanggung">
          <SmartNativeSelect id="rtp-ditanggung" value={borne} onChange={(e) => setBorne(e.target.value)} data-testid="rtp-borne">
            <option value="supplier">Pemasok (tagihan dipotong lewat nota debit)</option>
            <option value="da">DA (dibebankan; barang ditolak saat GR menjadi bisa ditagih pemasok)</option>
          </SmartNativeSelect>
        </Isian>
      )}
      {needGr && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="GR asal" wajib htmlFor="rtp-gr" petunjuk="Harga & pemasok diambil dari penerimaan ini.">
            <SmartNativeSelect id="rtp-gr" value={grId} onChange={(e) => { setGrId(e.target.value); setLineId(''); }} data-testid="rtp-gr">
              <option value="">— pilih GR —</option>
              {grs.map((g) => <option key={g.id} value={g.id}>{g.receipt_number} · {g.supplier_name || '-'}{g.po_number ? ` · ${g.po_number}` : ''}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Baris GR" wajib htmlFor="rtp-baris">
            <SmartNativeSelect id="rtp-baris" value={lineId} onChange={(e) => setLineId(e.target.value)} data-testid="rtp-gr-line">
              <option value="">— pilih baris —</option>
              {grLines.map((li) => (
                <option key={li.id || li.po_item_id} value={li.id || li.po_item_id}>
                  {li.sku || ''} {li.material_name || li.product_name} · @ {fmtRp(li.unit_price || li.unit_cost || 0)}
                </option>
              ))}
            </SmartNativeSelect>
          </Isian>
        </div>
      )}
      {!fromQ && (
        <Isian label="Lokasi asal stok" wajib htmlFor="rtp-lokasi"
          petunjuk={<span data-testid="rtp-location-hint">{lineMaterialId && stockLocs && stockLocs.length === 0
            ? 'Barang ini tidak punya stok di lokasi mana pun, jadi tidak bisa diretur dari stok. Bila barangnya ada di Karantina QC, buat retur dari layar Karantina.'
            : 'Hanya lokasi yang memegang stok barang baris GR terpilih.'}</span>}>
          <SmartNativeSelect id="rtp-lokasi" value={locId} onChange={(e) => setLocId(e.target.value)}
            disabled={!lineMaterialId || stockLocs === null || stockLocs.length === 0} data-testid="rtp-location">
            <option value="">
              {!lineMaterialId ? '— pilih baris GR dulu —'
                : stockLocs === null ? 'Memuat lokasi stok…'
                  : stockLocs.length === 0 ? '— tidak ada stok barang ini di lokasi mana pun —' : '— pilih lokasi —'}
            </option>
            {(stockLocs || []).map((l) => (
              <option key={l.id} value={l.id}>
                {`${l.code ? `${l.code} · ` : ''}${l.name || l.code || 'Lokasi'} — stok ${fmtNum(l.qty)} ${l.unit || ''}`.trim()}
              </option>
            ))}
          </SmartNativeSelect>
        </Isian>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Qty" wajib htmlFor="rtp-qty"
          petunjuk={price > 0 && Number(qty) > 0 ? `Nilai pada harga GR: ${fmtRp(Number(qty) * price)} (tanpa PPN — DA bukan PKP)` : undefined}>
          <Input id="rtp-qty" type="number" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)} data-testid="rtp-qty" />
        </Isian>
        <Isian label="Tanggal kirim">
          <DatePicker value={shipDate} onChange={setShipDate} placeholder="Belum ditentukan" testId="rtp-ship-date" />
        </Isian>
      </div>
      <Isian label="Alasan" wajib htmlFor="rtp-alasan">
        <Input id="rtp-alasan" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="mis. kain berlubang, salah warna" data-testid="rtp-reason" />
      </Isian>
      <Isian label="Tautan foto bukti" htmlFor="rtp-foto" petunjuk="Pisahkan beberapa tautan dengan spasi.">
        <Input id="rtp-foto" value={photos} onChange={(e) => setPhotos(e.target.value)} placeholder="https://..." data-testid="rtp-photos" />
      </Isian>
      <Isian label="Catatan" htmlFor="rtp-catatan">
        <Input id="rtp-catatan" value={notes} onChange={(e) => setNotes(e.target.value)} data-testid="rtp-notes" />
      </Isian>
    </FormPopup>
  );
}

function ReplacementModal({ token, rtp, onClose, onDone }) {
  const [locs, setLocs] = useState([]);
  const [locId, setLocId] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => { apiGet(token, '/api/rahaza/storage-locations').then(setLocs).catch((e) => setErr(e.message)); }, [token]);
  const submit = async () => {
    if (!locId) { setErr('Pilih lokasi penerima'); return; }
    setBusy(true); setErr('');
    try {
      await apiPost(token, `/api/rahaza/purchase-returns/${rtp.id}/receive-replacement`, { location_id: locId });
      toast.success(`Pengganti ${rtp.rtp_number} diterima`);
      onDone();
    } catch (e) { setErr(e.message); setBusy(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="rtp-replacement-form"
      judul={`Terima barang pengganti · ${rtp.rtp_number}`}
      keterangan="Barang pengganti masuk stok pada harga GR asal. Bagian yang dulu bernilai menutup klaim retur; bagian yang ditolak saat GR menjadi penerimaan susulan yang bisa ditagih pemasok."
      onSimpan={submit} menyimpan={busy} galat={err} labelSimpan="Terima pengganti">
      <Isian label="Lokasi penerima" wajib htmlFor="rtp-lokasi-pengganti">
        <SmartNativeSelect id="rtp-lokasi-pengganti" value={locId} onChange={(e) => setLocId(e.target.value)} data-testid="rtp-replacement-location">
          <option value="">— lokasi penerima —</option>
          {locs.map((l) => <option key={l.id} value={l.id}>{l.code ? `${l.code} · ` : ''}{l.name || l.code}</option>)}
        </SmartNativeSelect>
      </Isian>
    </FormPopup>
  );
}

const STATUS_PILIHAN = [['all', 'Semua'], ['draft', 'Draf'], ['awaiting_settlement', 'Menunggu penyelesaian'], ['settled', 'Selesai'], ['cancelled', 'Batal']];

export default function PurchaseReturnModule({ token }) {
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState('all');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [detail, setDetail] = useState(null);
  const [replacing, setReplacing] = useState(null);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const res = await apiGet(token, `/api/rahaza/purchase-returns?status=${status}`);
      setRows(res?.items || []);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [token, status]);
  useEffect(() => { load(); }, [load]);

  const act = async (rtp, path, msg) => {
    setBusy(rtp.id);
    try {
      const out = await apiPost(token, `/api/rahaza/purchase-returns/${rtp.id}/${path}`, {});
      const p = out?._posting;
      toast.success(`${msg} ${rtp.rtp_number}${p?.je_number ? ` · jurnal ${p.je_number}` : ''}${p && p.ok === false ? ` · jurnal GAGAL: ${p.error}` : ''}`);
      load();
    } catch (e) { toast.error(e.message); }
    finally { setBusy(''); }
  };

  const menungguKeuangan = (r) => (r.status === 'awaiting_settlement' && ['debit_note', 'destroy', 'refund'].includes(r.settlement))
    || (r.status === 'draft' && r.settlement === 'accept_discount');
  const aksiBaris = (r) => (
    <div className="flex flex-wrap justify-end gap-1">
      {r.status === 'draft' && SHIPPING.includes(r.settlement) && (
        <Button size="sm" disabled={busy === r.id} onClick={() => act(r, 'send', r.settlement === 'destroy' ? 'Dimusnahkan' : 'Dikirim')}
          data-testid={`rtp-send-${r.id}`}><Send />{r.settlement === 'destroy' ? 'Proses musnah' : 'Kirim'}</Button>
      )}
      {r.status === 'draft' && (
        <Button size="sm" variant="outline" disabled={busy === r.id} onClick={() => act(r, 'cancel', 'Dibatalkan')}
          title="Batalkan retur" aria-label="Batalkan retur" data-testid={`rtp-cancel-${r.id}`}><XCircle /></Button>
      )}
      {r.status === 'awaiting_settlement' && r.settlement === 'exchange' && (
        <Button size="sm" variant="success" onClick={() => setReplacing(r)} data-testid={`rtp-replace-${r.id}`}>
          <PackageCheck />Terima pengganti</Button>
      )}
      {menungguKeuangan(r) && (
        <span className="text-xs text-muted-foreground">Menunggu Keuangan ({r.settlement === 'refund' ? 'refund' : 'nota debit'})</span>
      )}
    </div>
  );

  const kolom = [
    { kunci: 'no', label: 'No. retur', hp: 'judul', isi: (r) => (
      <div>
        <p className="font-medium tabular-nums">{r.rtp_number}</p>
        <p className="text-xs text-muted-foreground">{fmtDate(r.created_at)}</p>
      </div>) },
    { kunci: 'pemasok', label: 'Pemasok · GR', hp: 'keterangan', isi: (r) => (
      <div className="text-sm">{r.supplier_name || '-'}
        <div className="text-xs text-muted-foreground">{r.gr_number}{r.po_number ? ` · ${r.po_number}` : ''}</div>
      </div>) },
    { kunci: 'penyelesaian', label: 'Penyelesaian', isi: (r) => (
      <div className="text-sm">{settlementLabel(r.settlement)}{r.settlement === 'destroy' ? ` (${r.destroy_borne_by === 'da' ? 'DA' : 'pemasok'})` : ''}
        {r.debit_note_number && <div className="text-xs text-muted-foreground">ND {r.debit_note_number}</div>}
      </div>) },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtNum(r.total_qty)}</span> },
    { kunci: 'nilai', label: 'Nilai (harga GR)', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtRp(r.total_amount)}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusBadge status={r.status} /> },
    { kunci: 'umur', label: 'Umur', rata: 'kanan', isi: (r) => (
      <span className={`tabular-nums ${r.status === 'awaiting_settlement' && r.age_days >= 14 ? 'font-medium text-[hsl(var(--danger-text))]' : ''}`}>{r.age_days} hari</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: aksiBaris },
  ];

  return (
    <PageLayout testId="purchase-return-module" title="Retur Pembelian"
      subtitle="Barang dikembalikan ke pemasok pada harga GR asal; nota debit & refund diselesaikan Keuangan."
      actions={<Button onClick={() => setShowCreate(true)} data-testid="rtp-new"><Plus />Retur dari stok</Button>}
      filters={<>
        {<FilterChips className="w-full sm:w-auto" options={STATUS_PILIHAN.map(([key, label]) => ({ key, label }))} value={status} onChange={setStatus}
        hideWhenEmpty={false} testId="rtp-filter" />}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {<>
        <TombolUnduh namaBerkas="retur-pembelian" namaLembar="Retur pembelian" baris={rows} testId="rtp-unduh"
          kolom={[
            { label: 'No. retur', nilai: (r) => r.rtp_number },
            { label: 'Tanggal', nilai: (r) => fmtDate(r.created_at) },
            { label: 'Pemasok', nilai: (r) => r.supplier_name || '' },
            { label: 'No. GR', nilai: (r) => r.gr_number || '' },
            { label: 'No. PO', nilai: (r) => r.po_number || '' },
            { label: 'Penyelesaian', nilai: (r) => settlementLabel(r.settlement) },
            { label: 'Nota debit', nilai: (r) => r.debit_note_number || '' },
            { label: 'Qty', nilai: (r) => Number(r.total_qty || 0) },
            { label: 'Nilai (Rp)', nilai: (r) => Number(r.total_amount || 0) },
            { label: 'Status', nilai: (r) => statusLabel(r.status) },
            { label: 'Umur (hari)', nilai: (r) => Number(r.age_days || 0) },
          ]} />
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={load} disabled={loading}>
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
        </div>
      </>}>
      {err && <p className="text-sm text-[hsl(var(--danger-text))]" role="alert">{err}</p>}
      {loading && rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat retur pembelian…</p>
      ) : (
        <TabelData kolom={kolom} baris={rows} onKlikBaris={setDetail} testId="rtp-table"
          kosong={<EmptyState title="Belum ada retur pembelian"
            description={status === 'all' ? 'Retur dibuat dari Karantina QC atau dengan tombol "Retur dari stok".' : 'Tidak ada retur dengan status ini.'} />} />
      )}

      {showCreate && (
        <PurchaseReturnCreateModal token={token} onClose={() => setShowCreate(false)}
          onSaved={() => { setShowCreate(false); load(); }} />
      )}
      {replacing && (
        <ReplacementModal token={token} rtp={replacing} onClose={() => setReplacing(null)}
          onDone={() => { setReplacing(null); load(); }} />
      )}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={`Retur pembelian ${detail.rtp_number}`} testId="rtp-detail"
          status={<StatusBadge status={detail.status} />}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Pemasok">{detail.supplier_name || '—'}</BarisDetail>
            <BarisDetail label="GR / PO">{detail.gr_number}{detail.po_number ? ` · ${detail.po_number}` : ''}</BarisDetail>
            <BarisDetail label="Penyelesaian">{settlementLabel(detail.settlement)}</BarisDetail>
            <BarisDetail label="Alasan">{detail.reason || '—'}</BarisDetail>
          </dl>
          <div className="overflow-x-auto">
            <Table className="min-w-[40rem]">
              <TableHeader>
                <TableRow>
                  <TableHead>Material</TableHead><TableHead>Sumber</TableHead><TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Harga GR</TableHead><TableHead className="text-right">Bernilai / belum</TableHead>
                  <TableHead className="text-right">Klaim</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(detail.lines || []).map((ln) => (
                  <TableRow key={ln.id}>
                    <TableCell>{ln.material_code} · {ln.material_name}</TableCell>
                    <TableCell>{ln.source === 'quarantine' ? 'Karantina' : 'Stok'}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtNum(ln.qty)} {ln.unit}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtRp(ln.gr_price)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtNum(ln.valued_qty ?? ln.valued_qty_est)} / {fmtNum(ln.unvalued_qty ?? ln.unvalued_qty_est)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtRp(ln.claim_amount || 0)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {(detail.journals || []).length > 0 && (
            <div className="text-sm">
              <p className="mb-1 font-medium">Jurnal</p>
              {detail.journals.map((j, i) => (
                <p key={i} className="text-muted-foreground">{TAHAP_JURNAL[j.stage] || j.stage}: {j.je_number || (j.skipped ? 'tanpa jurnal' : `GAGAL — ${j.error || ''}`)}</p>
              ))}
            </div>
          )}
          <div className="text-sm">
            <p className="mb-1 font-medium">Riwayat</p>
            {(detail.history || []).map((h, i) => (
              <p key={i} className="text-muted-foreground">{fmtDate(h.at)} · {h.by} · {AKSI_RIWAYAT[h.action] || h.action}{h.note ? ` — ${h.note}` : ''}</p>
            ))}
          </div>
        </DetailPopup>
      )}
    </PageLayout>
  );
}

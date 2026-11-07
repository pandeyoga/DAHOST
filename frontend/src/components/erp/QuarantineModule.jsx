/**
 * Karantina QC — Portal Gudang (FASE 6 / INV-8)
 *
 * Barang yang DITOLAK QC tidak lagi hilang tanpa jejak: qty reject masuk ke
 * lokasi KARANTINA (stok fisik tercatat tapi DIBLOKIR — tidak bisa dipakai
 * produksi/penjualan), lalu ditindaklanjuti lewat 3 disposisi:
 *   • Lepas ke Stok      → lolos re-inspeksi / setelah rework. Reject GR yang dilepas =
 *                          PENERIMAAN SUSULAN (2026-11-02, K11): Dr persediaan / Cr GRNI pada
 *                          harga GR/PO (harga potongan diketik Keuangan), bisa ditagih pemasok.
 *   • Buat Retur Pembelian → dokumen RTP (Pengadaan) dengan penyelesaian tukar / nota debit /
 *                          refund / diterima dengan diskon / dimusnahkan (K11) — menggantikan
 *                          tombol "Retur supplier" lama. Disposisi lama tampil sebagai
 *                          "Retur lama tanpa penyelesaian".
 *   • Scrap (Buang)      → write-off (jurnal kerugian bila barang sudah bernilai)
 *
 * Sumber data: /api/wms/quarantine (+ /summary, /location, /reject-categories)
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout; tab buatan → pil penyaring; kartu angka StatTile
 * (kartu "Qty tertahan" disembunyikan: menjumlah satuan berbeda); tabel + unduhan; aksi baris maks 2
 * (sisanya "Lainnya" & popup detail); form lepas/scrap/manual = FormPopup; detail baris = DetailPopup.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { materialOptionLabel } from '@/lib/materialFields';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { toast } from 'sonner';
import {
  RefreshCw, Search, PackageCheck, Undo2, Trash2, Info, PackagePlus,
  ShieldOff, Lock, MoreHorizontal,
} from 'lucide-react';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import { PurchaseReturnCreateModal } from './procurement/PurchaseReturnModule';

const API = process.env.REACT_APP_BACKEND_URL || '';

async function api(method, path, token, body) {
  const opts = { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(`${API}${path}`, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
}

const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID');
const fmtRp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
const fmtDate = (iso) => {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return String(iso).slice(0, 16); }
};

const SOURCE_LABEL = {
  goods_receipt: 'Penerimaan (GR)',
  grn_inspection: 'Re-inspeksi QC',
  manual: 'Temuan gudang',
};
const sourceLabel = (t) => SOURCE_LABEL[t] || t || '-';

/** Kotak status ketersediaan satu item (dipakai di tabel & popup detail). */
function TandaBlokir({ it }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {Number(it.legacy_return_qty || 0) > 0 && (
        <span title="Retur ke pemasok sebelum ada dokumen Retur Pembelian — belum tercatat penyelesaiannya (tukar / nota debit / refund). Selesaikan manual bersama Keuangan."
          data-testid={`quarantine-legacy-return-${it.id}`}>
          <StatusBadge tone="primary" label={`Retur lama tanpa penyelesaian · ${fmtNum(it.legacy_return_qty)} ${it.unit}`} />
        </span>
      )}
      {it.availability_blocked === false ? (
        <span title={`Barang reject ini MASIH terhitung tersedia sebanyak ${fmtNum(it.availability_shortfall)} ${it.unit} — bisa ikut dipakai produksi atau terkirim ke pembeli.`}
          data-testid={`quarantine-unblocked-badge-${it.id}`}>
          <StatusBadge tone="danger" label="Tidak terblokir" />
        </span>
      ) : it.status === 'open' ? (
        <span title="Ketersediaan terblokir penuh — barang ini tidak bisa dipakai produksi/penjualan."
          data-testid={`quarantine-blocked-badge-${it.id}`}>
          <StatusBadge tone="success" label="Terblokir" />
        </span>
      ) : null}
    </span>
  );
}

function ActionModal({ item, action, locations, quarantineLoc, onClose, onSubmit }) {
  const CONF = {
    release: {
      title: 'Lepas ke stok', label: 'Lepas ke stok',
      desc: 'Barang lolos re-inspeksi / sudah di-rework. Stok akan kembali TERSEDIA di lokasi tujuan.',
      needLoc: true,
    },
    scrap: {
      title: 'Scrap (buang)', label: 'Scrap barang',
      desc: 'Barang dibuang. Bila barang sudah masuk nilai persediaan, jurnal kerugian (write-off) akan di-posting otomatis.',
      needLoc: false,
    },
  }[action];

  const [qty, setQty] = useState(item.remaining_qty);
  // 2026-11-02 — No.18(a): tidak ada lokasi bawaan (dulu item pertama = zona uji "ZU").
  const [toLoc, setToLoc] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  // 2026-11-02 (K11): lepas reject GR = penerimaan susulan — harga bawaan = harga GR/PO;
  // harga potongan hanya boleh diketik Keuangan (backend menolak bila bukan Keuangan).
  const lateReceipt = action === 'release' && item.source?.type === 'goods_receipt'
    && Number(item.valued_remaining_qty || 0) < Number(item.remaining_qty || 0) - 1e-6;
  const [price, setPrice] = useState(item.unit_cost || '');

  const submit = async () => {
    const q = parseFloat(qty);
    if (!q || q <= 0) { setErr('Qty harus lebih dari 0'); return; }
    if (q > Number(item.remaining_qty) + 1e-6) { setErr(`Qty melebihi sisa karantina (${fmtNum(item.remaining_qty)})`); return; }
    if (CONF.needLoc && !toLoc) { setErr('Pilih lokasi tujuan'); return; }
    setBusy(true); setErr('');
    try {
      const payload = { qty: q, to_location_id: CONF.needLoc ? toLoc : undefined, notes };
      if (lateReceipt && price !== '' && Number(price) !== Number(item.unit_cost || 0)) payload.unit_price = Number(price);
      await onSubmit(payload);
    } catch (e) { setErr(e.message); setBusy(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="quarantine-action"
      judul={CONF.title} keterangan={`${item.material_code} · ${item.material_name}`}
      onSimpan={submit} menyimpan={busy} galat={err} labelSimpan={CONF.label}>
      <p className="text-sm text-muted-foreground">{CONF.desc}</p>
      <Isian label={`Qty (${item.unit})`} wajib htmlFor="q-act-qty" petunjuk={`Sisa karantina ${fmtNum(item.remaining_qty)} ${item.unit}.`}>
        <Input id="q-act-qty" type="number" min="0" step="0.01" value={qty} onChange={(e) => setQty(e.target.value)}
          data-testid="quarantine-action-qty" />
      </Isian>
      {CONF.needLoc && (
        <Isian label="Lokasi tujuan" wajib htmlFor="q-act-lokasi"
          petunjuk={`Lokasi karantina (${quarantineLoc?.name || 'Area Karantina QC'}) tidak bisa dipilih sebagai tujuan.`}>
          <SmartNativeSelect id="q-act-lokasi" value={toLoc} onChange={(e) => setToLoc(e.target.value)} data-testid="quarantine-action-location">
            <option value="">— Pilih lokasi tujuan —</option>
            {locations.map((l) => <option key={l.id} value={l.id}>{l.code ? `${l.code} · ` : ''}{l.name || l.code}</option>)}
          </SmartNativeSelect>
        </Isian>
      )}
      <Isian label="Catatan" htmlFor="q-act-catatan">
        <Textarea id="q-act-catatan" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)}
          placeholder="Alasan / keterangan tindak lanjut…" data-testid="quarantine-action-notes" />
      </Isian>
      {lateReceipt && (
        <Isian label="Harga satuan (Rp)" htmlFor="q-act-harga" petunjuk="Bawaan harga GR/PO; harga potongan hanya diketik Keuangan.">
          <Input id="q-act-harga" type="number" min="0" step="any" value={price} onChange={(e) => setPrice(e.target.value)}
            data-testid="quarantine-action-price" />
        </Isian>
      )}
      {!item.valued && action !== 'release' && (
        <Notice tone="info" icon={Info}>
          Barang ini <strong>belum masuk nilai persediaan</strong> (reject saat penerimaan tidak ditagihkan supplier),
          jadi tidak ada jurnal keuangan yang dibuat.
        </Notice>
      )}
      {lateReceipt && (
        <Notice tone="info" icon={Info}>
          Dicatat sebagai <strong>penerimaan susulan</strong> pada GR {item.source?.number || ''}: Persediaan (Dr) /
          Hutang Belum Ditagih GRNI (Cr) sebesar qty × harga, HPP rata-rata diperbarui, dan qty ini
          bisa ditagih pemasok lewat Tagihan dari GR.
        </Notice>
      )}
      {!item.valued && action === 'release' && !lateReceipt && (
        <Notice tone="info" icon={Info}>
          Barang akan <strong>dikapitalisasi</strong> ke nilai persediaan (jurnal penyesuaian otomatis).
        </Notice>
      )}
    </FormPopup>
  );
}

function ManualModal({ token, locations, onClose, onSaved }) {
  const [materials, setMaterials] = useState([]);
  const [reasons, setReasons] = useState([]);
  // 2026-11-07 (Tahap 5): lokasi asal TIDAK dipilihkan (dulu otomatis lokasi pertama — melanggar aturan owner
  // No.18(a) "pengguna wajib memilih lokasi"; barang bisa tercatat keluar dari rak yang salah).
  const [form, setForm] = useState({ material_id: '', qty: '', from_location_id: '', reason_code: '', notes: '', unit: 'pcs' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const m = await api('GET', '/api/rahaza/materials?limit=500', token);
        setMaterials(Array.isArray(m) ? m : (m.items || []));
      } catch { /* noop */ }
      try { setReasons(await api('GET', '/api/wms/quarantine/reject-categories', token)); } catch { /* noop */ }
    })();
  }, [token]);

  const save = async () => {
    if (!form.material_id || !form.qty || !form.from_location_id) { setErr('Material, qty, dan lokasi asal wajib diisi'); return; }
    setBusy(true); setErr('');
    try {
      const mat = materials.find((m) => m.id === form.material_id);
      await api('POST', '/api/wms/quarantine/manual', token, { ...form, qty: parseFloat(form.qty), unit: mat?.unit || 'pcs' });
      onSaved();
    } catch (e) { setErr(e.message); setBusy(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="quarantine-manual"
      judul="Karantina manual"
      keterangan="Pindahkan stok yang sudah ada di gudang ke Karantina QC (mis. ditemukan rusak saat penyimpanan)."
      onSimpan={save} menyimpan={busy} galat={err} labelSimpan="Karantina">
      <Isian label="Material" wajib htmlFor="q-man-material">
        <SmartNativeSelect id="q-man-material" value={form.material_id} onChange={(e) => setForm({ ...form, material_id: e.target.value })}
          data-testid="quarantine-manual-material">
          <option value="">— pilih material —</option>
          {materials.map((m) => <option key={m.id} value={m.id}>{materialOptionLabel(m)}</option>)}
        </SmartNativeSelect>
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Qty" wajib htmlFor="q-man-qty">
          <Input id="q-man-qty" type="number" min="0" step="0.01" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })}
            data-testid="quarantine-manual-qty" />
        </Isian>
        <Isian label="Lokasi asal" wajib htmlFor="q-man-lokasi">
          <SmartNativeSelect id="q-man-lokasi" value={form.from_location_id} onChange={(e) => setForm({ ...form, from_location_id: e.target.value })}
            data-testid="quarantine-manual-location">
            <option value="">— pilih lokasi asal —</option>
            {locations.map((l) => <option key={l.id} value={l.id}>{`${l.code ? `${l.code} · ` : ''}${l.name || l.code}`}</option>)}
          </SmartNativeSelect>
        </Isian>
      </div>
      <Isian label="Alasan" htmlFor="q-man-alasan">
        <SmartNativeSelect id="q-man-alasan" value={form.reason_code} onChange={(e) => setForm({ ...form, reason_code: e.target.value })}
          data-testid="quarantine-manual-reason">
          <option value="">— pilih alasan —</option>
          {reasons.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
        </SmartNativeSelect>
      </Isian>
      <Isian label="Catatan" htmlFor="q-man-catatan">
        <Textarea id="q-man-catatan" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
          data-testid="quarantine-manual-notes" />
      </Isian>
    </FormPopup>
  );
}

export default function QuarantineModule({ token: tokenProp }) {
  const token = tokenProp || localStorage.getItem('token') || '';
  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState(null);
  const [locInfo, setLocInfo] = useState(null);
  const [status, setStatus] = useState('open');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [modal, setModal] = useState(null);     // {item, action}
  const [showManual, setShowManual] = useState(false);
  const [detail, setDetail] = useState(null);
  const [reasonLabels, setReasonLabels] = useState({});   // kode alasan reject → label staf
  // "Perlu Tindakan Manual" = hanya item yang ketersediaannya BELUM terblokir,
  // yaitu barang reject yang MASIH terhitung tersedia dan bisa ikut dipakai
  // produksi / terkirim ke pembeli. Dulu kegagalan blokir hanya tercatat di log
  // server, jadi tak ada satu pun layar yang bisa menunjukkannya.
  const [needsAction, setNeedsAction] = useState(false);
  const [retrying, setRetrying] = useState('');
  // 2026-11-02 (K11): "Buat Retur Pembelian" menggantikan "Retur supplier"; tab retur lama
  const [rtpItem, setRtpItem] = useState(null);
  const [legacyOnly, setLegacyOnly] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const qs = legacyOnly ? 'legacy_returns=true'
        : `status=${status}${needsAction ? '&needs_action=true' : ''}`;
      const [list, sm] = await Promise.all([
        api('GET', `/api/wms/quarantine?${qs}`, token),
        api('GET', '/api/wms/quarantine/summary', token),
      ]);
      setItems(Array.isArray(list) ? list : []);
      setSummary(sm || null);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [token, status, needsAction, legacyOnly]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    (async () => {
      try { setLocInfo(await api('GET', '/api/wms/quarantine/location', token)); }
      catch { /* noop */ }
      try {
        const cats = await api('GET', '/api/wms/quarantine/reject-categories', token);
        setReasonLabels(Object.fromEntries((Array.isArray(cats) ? cats : []).map((c) => [c.code, c.label])));
      } catch { /* label alasan gagal dimuat — kode tetap tampil */ }
    })();
  }, [token]);

  const storageLocs = useMemo(() => (locInfo?.storage_locations || []), [locInfo]);
  const alasan = (code) => reasonLabels[code] || code;

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) => `${it.material_code} ${it.material_name} ${it.source?.number || ''} ${it.source?.supplier_name || ''}`.toLowerCase().includes(q));
  }, [items, search]);
  const pg = useClientPagination(filtered, 25);

  const doAction = async (payload) => {
    const { item, action } = modal;
    const path = action === 'release' ? 'release' : 'scrap';
    const res = await api('POST', `/api/wms/quarantine/${item.id}/${path}`, token, payload);
    setModal(null);
    setDetail(null);
    const p = res.posting || {};
    const jeMsg = p.je_number ? ` · jurnal ${p.je_number} di-posting`
      : (p.skipped ? ' · tanpa jurnal keuangan' : (p.ok === false ? ` · jurnal GAGAL: ${p.error || ''}` : ''));
    const lateMsg = res.late_receipt ? ` · penerimaan susulan @ ${fmtRp(res.unit_price)} (bisa ditagih)` : '';
    toast.success(`${action === 'release' ? 'Dilepas ke stok' : 'Di-scrap'} ${fmtNum(payload.qty)} ${item.unit}${jeMsg}${lateMsg}`, { duration: 6000 });
    load();
  };

  const dispLabel = (d) => {
    if (d.action === 'release') return 'Dilepas';
    if (d.action === 'purchase_return') return `Retur Pembelian ${d.rtp_number || ''}`;
    if (d.action === 'return_supplier') return d.purchase_return_id ? 'Retur supplier' : 'Retur lama tanpa penyelesaian';
    return d.purchase_return_id ? `Dimusnahkan (${d.rtp_number || 'RTP'})` : 'Scrap';
  };

  // Coba blokir ulang ketersediaan — supaya daftar "Perlu Tindakan Manual" bisa
  // DITINDAK dari layar, bukan hanya diberitahukan (dulu harus lewat database).
  const retryBlock = async (it) => {
    setRetrying(it.id); setErr('');
    try {
      const res = await api('POST', `/api/wms/quarantine/${it.id}/retry-block`, token);
      toast.success(res.pesan || 'Blokir ketersediaan berhasil dipasang ulang.', { duration: 6000 });
      setDetail(null);
      await load();
    } catch (e) { setErr(e.message); }
    finally { setRetrying(''); }
  };

  const unblockedCount = Number(summary?.unblocked_items || 0);
  const unblockedQty = Number(summary?.unblocked_qty || 0);
  // Penyaring tampilan (dulu tiga tab buatan bergaris bawah) — urutan & perilaku sama.
  const tampilan = legacyOnly ? 'legacy' : needsAction ? 'needs' : 'all';
  const pilihTampilan = (k) => {
    if (k === 'legacy') { setNeedsAction(false); setLegacyOnly(true); }
    else if (k === 'needs') { setStatus('open'); setLegacyOnly(false); setNeedsAction(true); }
    else { setNeedsAction(false); setLegacyOnly(false); }
  };
  const adaData = summary && (Number(summary.open_items || 0) + Number(summary.closed_items || 0)) > 0;

  // Dari popup detail: popup detail ditutup dulu, lalu form tindak lanjut dibuka (tidak ada dua popup bertumpuk).
  const buka = (fn, dariDetail) => () => { if (dariDetail) setDetail(null); fn(); };
  const tombolLepas = (it, dariDetail = false) => (
    <Button size="sm" variant="success" onClick={buka(() => setModal({ item: it, action: 'release' }), dariDetail)}
      data-testid={`quarantine-release-${it.id}`}>
      <PackageCheck />Lepas
    </Button>
  );
  const tombolBlokir = (it) => (
    <Button size="sm" variant="destructive" onClick={() => retryBlock(it)} disabled={retrying === it.id}
      title="Pasang ulang blokir ketersediaan agar barang reject ini tidak terhitung tersedia"
      data-testid={`quarantine-retry-block-${it.id}`}>
      <ShieldOff />{retrying === it.id ? 'Memblokir…' : 'Coba blokir ulang'}
    </Button>
  );
  const aksiBaris = (it) => {
    if (it.status !== 'open') {
      return (
        <div className="text-right text-xs text-muted-foreground" data-testid={`quarantine-history-${it.id}`}>
          {(it.dispositions || []).map((d) => <div key={d.id}>{dispLabel(d)} {fmtNum(d.qty)} · {d.by || '-'}</div>)}
        </div>
      );
    }
    const blokirDulu = it.availability_blocked === false;
    return (
      <div className="flex items-center justify-end gap-1.5">
        {blokirDulu ? tombolBlokir(it) : tombolLepas(it)}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="outline" aria-label="Tindak lanjut lainnya" title="Tindak lanjut lainnya"
              data-testid={`quarantine-more-${it.id}`}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {blokirDulu && (
              <DropdownMenuItem onSelect={() => setModal({ item: it, action: 'release' })} data-testid={`quarantine-release-${it.id}`}>
                <PackageCheck className="mr-2 h-4 w-4" />Lepas ke stok
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={() => setRtpItem(it)} data-testid={`quarantine-return-${it.id}`}>
              <Undo2 className="mr-2 h-4 w-4" />Buat retur pembelian
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setModal({ item: it, action: 'scrap' })} data-testid={`quarantine-scrap-${it.id}`}
              className="text-[hsl(var(--danger-text))]">
              <Trash2 className="mr-2 h-4 w-4" />Scrap (buang)
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    );
  };

  const kolom = [
    { kunci: 'material', label: 'Material', hp: 'judul', isi: (it) => (
      <div className="min-w-0" data-testid={`quarantine-row-${it.id}`}>
        <p className="font-medium">{it.material_name || '-'}</p>
        <p className="text-xs tabular-nums text-muted-foreground">{it.material_code}</p>
        <div className="mt-1"><TandaBlokir it={it} /></div>
      </div>) },
    { kunci: 'sumber', label: 'Sumber', hp: 'keterangan', isi: (it) => (
      <div className="text-sm">
        <div>{sourceLabel(it.source?.type)}</div>
        {(it.source?.number || it.source?.supplier_name) && (
          <div className="text-xs text-muted-foreground">{[it.source?.number, it.source?.supplier_name].filter(Boolean).join(' · ')}</div>
        )}
      </div>) },
    { kunci: 'alasan', label: 'Alasan', isi: (it) => ((it.reject_reasons || []).length === 0
      ? <span className="text-muted-foreground">-</span>
      : <div className="text-sm">{(it.reject_reasons || []).map((r, i) => <div key={i}>{alasan(r.code)}{r.qty ? ` · ${fmtNum(r.qty)}` : ''}</div>)}</div>) },
    { kunci: 'qty', label: 'Qty reject', rata: 'kanan', isi: (it) => <span className="tabular-nums">{fmtNum(it.qty)} <span className="text-xs text-muted-foreground">{it.unit}</span></span> },
    { kunci: 'sisa', label: 'Sisa', rata: 'kanan', isi: (it) => <span className="font-medium tabular-nums">{fmtNum(it.remaining_qty)}</span> },
    { kunci: 'nilai', label: 'Nilai', rata: 'kanan', isi: (it) => (
      <div className="text-sm">
        {Number(it.unit_cost || 0) > 0 ? <span className="tabular-nums">{fmtRp(it.value)}</span> :
          <span className="text-[hsl(var(--warning-text))]" title="Harga satuan material belum diisi — jurnal keuangan akan dilewati">harga belum diisi</span>}
        <div className="text-xs text-muted-foreground">{it.valued ? 'sudah bernilai' : 'belum bernilai'}</div>
      </div>) },
    { kunci: 'umur', label: 'Umur', rata: 'kanan', isi: (it) => (
      <div className="text-sm">
        <span className={Number(it.age_days) >= 14 ? 'font-medium text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}>{fmtNum(it.age_days)} hari</span>
        <div className="text-xs text-muted-foreground">{fmtDate(it.created_at)}</div>
      </div>) },
    { kunci: 'aksi', label: 'Tindak lanjut', rata: 'kanan', hp: 'aksi', isi: aksiBaris },
  ];

  return (
    <PageLayout testId="quarantine-module" title="Karantina QC"
      subtitle="Barang reject QC ditahan & diblokir sampai dilepas, diretur ke pemasok, atau di-scrap."
      actions={<Button onClick={() => setShowManual(true)} data-testid="quarantine-manual-btn"><PackagePlus />Karantina manual</Button>}
      filters={<>
        <FilterChips value={tampilan} onChange={pilihTampilan} hideWhenEmpty={false} testId="quarantine-tab"
          options={[
            { key: 'all', label: 'Semua item karantina' },
            { key: 'legacy', label: 'Retur lama tanpa penyelesaian' },
            { key: 'needs', label: 'Perlu tindakan manual', count: unblockedCount },
          ]} />
        <SmartNativeSelect value={status} onChange={(e) => setStatus(e.target.value)} disabled={needsAction || legacyOnly}
          className="w-full sm:w-44" data-testid="quarantine-status-filter" aria-label="Status karantina">
          <option value="open">Masih tertahan</option>
          <option value="closed">Sudah selesai</option>
          <option value="all">Semua status</option>
        </SmartNativeSelect>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari material, no. GR, supplier"
            className="pl-8" data-testid="quarantine-search" />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="karantina-qc" namaLembar="Karantina QC" baris={filtered} testId="quarantine-unduh"
          kolom={[
            { label: 'Kode material', nilai: (it) => it.material_code },
            { label: 'Material', nilai: (it) => it.material_name },
            { label: 'Sumber', nilai: (it) => sourceLabel(it.source?.type) },
            { label: 'No. dokumen', nilai: (it) => it.source?.number || '' },
            { label: 'Pemasok', nilai: (it) => it.source?.supplier_name || '' },
            { label: 'Alasan', nilai: (it) => (it.reject_reasons || []).map((r) => `${alasan(r.code)}${r.qty ? ` ${r.qty}` : ''}`).join('; ') },
            { label: 'Satuan', nilai: (it) => it.unit },
            { label: 'Qty reject', nilai: (it) => Number(it.qty || 0) },
            { label: 'Sisa', nilai: (it) => Number(it.remaining_qty || 0) },
            { label: 'Nilai (Rp)', nilai: (it) => (Number(it.unit_cost || 0) > 0 ? Number(it.value || 0) : '') },
            { label: 'Bernilai', nilai: (it) => (it.valued ? 'Sudah' : 'Belum') },
            { label: 'Ketersediaan', nilai: (it) => (it.availability_blocked === false ? 'Tidak terblokir' : it.status === 'open' ? 'Terblokir' : '') },
            { label: 'Umur (hari)', nilai: (it) => Number(it.age_days || 0) },
            { label: 'Masuk karantina', nilai: (it) => fmtDate(it.created_at) },
            { label: 'Status', nilai: (it) => (it.status === 'open' ? 'Masih tertahan' : 'Sudah selesai') },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="quarantine-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {/* PERINGATAN MERAH — barang reject yang ketersediaannya BELUM terblokir: masih terhitung TERSEDIA
            (`available = qty − reserved`), jadi bisa ikut dipilih untuk produksi atau DIKIRIM KE PEMBELI. */}
        {unblockedCount > 0 && (
          <Notice tone="danger" icon={ShieldOff} testId="quarantine-unblocked-banner"
            title={`Ketersediaan belum terblokir — ${fmtNum(unblockedCount)} item karantina (${fmtNum(unblockedQty)} unit)`}
            action={!needsAction && (
              <Button size="sm" variant="destructive" onClick={() => pilihTampilan('needs')} data-testid="quarantine-show-needs-action">
                Lihat daftar
              </Button>
            )}>
            Barang reject ini masih terhitung stok tersedia, sehingga bisa ikut dipilih untuk produksi atau terkirim ke
            pembeli. Tekan <em>Coba blokir ulang</em> pada barisnya. Bila tetap gagal, stok fisik di lokasi karantina
            kemungkinan lebih kecil dari qty karantina — lakukan opname/koreksi stok dulu.
            {(summary?.unblocked_groups || []).length > 0 && (
              <span className="mt-1 block tabular-nums">
                {(summary.unblocked_groups || []).map((g) => `${g.material_code || g.material_id} · belum terblokir ${fmtNum(g.shortfall)} ${g.unit}`).join(' · ')}
              </span>
            )}
          </Notice>
        )}
        {adaData && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Item tertahan" value={fmtNum(summary?.open_items)} testId="quarantine-stat-items"
              sub={`${fmtNum(summary?.closed_items)} item sudah selesai`} />
            <StatTile label="Nilai tertahan" value={fmtRp(summary?.open_value)} testId="quarantine-stat-value"
              sub={`Sisa × harga satuan · ${fmtNum(summary?.valued_items)} sudah bernilai, ${fmtNum(summary?.unvalued_items)} belum`} />
            <StatTile label="Item tertua" value={`${fmtNum(summary?.oldest_age_days)} hari`} testId="quarantine-stat-oldest"
              sub="Umur item terlama yang masih tertahan" />
            <StatTile label="Tindak lanjut tercatat" value={fmtNum(summary?.dispositions_total)} testId="quarantine-stat-dispositions"
              sub="Lepas, retur, dan scrap sejak awal" />
          </div>
        )}
        {summary && Object.keys(summary.by_reason || {}).length > 0 && (
          <p className="text-sm text-muted-foreground" data-testid="quarantine-by-reason">
            Alasan reject (sisa tertahan): {Object.entries(summary.by_reason).map(([code, qty]) => `${alasan(code)} ${fmtNum(qty)}`).join(' · ')}
          </p>
        )}
        {locInfo && (
          <p className="text-xs text-muted-foreground">Lokasi karantina: <span className="tabular-nums">{locInfo.code}</span> · {locInfo.name}</p>
        )}
      </>}
      footer={<>
        {pg.total > 0 && <PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total} pageSize={pg.pageSize} onPageChange={pg.setPage} />}
        <p className="text-xs text-muted-foreground">
          Cara kerja: saat Penerimaan Barang dikonfirmasi diterima, qty yang diterima masuk stok normal dan qty reject
          otomatis masuk Karantina QC. Bila reject baru ditemukan setelah barang masuk, pakai re-inspeksi QC pada GR
          (opsi lanjutkan meski sudah diterima) — stok otomatis dipindah ke karantina.
        </p>
      </>}>
      {err && <Notice tone="danger" title={err} />}

      {loading && items.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat karantina…</p>
      ) : (
        <TabelData kolom={kolom} baris={pg.paged} onKlikBaris={setDetail} testId="quarantine-table"
          kosong={needsAction ? (
            <EmptyState icon={Lock} title="Semua barang karantina sudah terblokir"
              description="Tidak ada barang reject yang masih terhitung tersedia: seluruh stok karantina tidak bisa dipakai produksi maupun dikirim ke pembeli." />
          ) : (
            <EmptyState icon={PackageCheck} title={search ? 'Tidak ada item yang cocok' : 'Tidak ada barang di karantina'}
              description={search ? 'Ubah kata pencarian.' : 'Qty reject dari penerimaan barang akan otomatis muncul di sini.'} />
          )} />
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} testId="quarantine-detail"
          judul={`${detail.material_code} · ${detail.material_name || '-'}`}
          status={<StatusBadge tone={detail.status === 'open' ? 'warning' : 'muted'} label={detail.status === 'open' ? 'Masih tertahan' : 'Sudah selesai'} />}
          aksi={detail.status === 'open' ? <>
            {detail.availability_blocked === false && tombolBlokir(detail)}
            {tombolLepas(detail, true)}
            <Button size="sm" variant="outline" onClick={buka(() => setRtpItem(detail), true)}><Undo2 />Buat retur pembelian</Button>
            <Button size="sm" variant="destructive" onClick={buka(() => setModal({ item: detail, action: 'scrap' }), true)}><Trash2 />Scrap</Button>
          </> : null}>
          <TandaBlokir it={detail} />
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Sumber">{sourceLabel(detail.source?.type)}{detail.source?.number ? ` · ${detail.source.number}` : ''}</BarisDetail>
            <BarisDetail label="Pemasok">{detail.source?.supplier_name || '—'}</BarisDetail>
            <BarisDetail label="Alasan reject">
              {(detail.reject_reasons || []).length ? (detail.reject_reasons || []).map((r) => `${alasan(r.code)}${r.qty ? ` · ${fmtNum(r.qty)}` : ''}`).join('; ') : '—'}
            </BarisDetail>
            <BarisDetail label="Qty reject">{fmtNum(detail.qty)} {detail.unit}</BarisDetail>
            <BarisDetail label="Sisa karantina">{fmtNum(detail.remaining_qty)} {detail.unit}</BarisDetail>
            <BarisDetail label="Nilai">
              {Number(detail.unit_cost || 0) > 0 ? fmtRp(detail.value) : 'Harga satuan belum diisi'} · {detail.valued ? 'sudah bernilai' : 'belum bernilai'}
            </BarisDetail>
            <BarisDetail label="Masuk karantina">{fmtDate(detail.created_at)} · {fmtNum(detail.age_days)} hari</BarisDetail>
            {(detail.dispositions || []).length > 0 && (
              <BarisDetail label="Tindak lanjut">
                {(detail.dispositions || []).map((d) => <div key={d.id}>{dispLabel(d)} {fmtNum(d.qty)} · {d.by || '-'}</div>)}
              </BarisDetail>
            )}
          </dl>
        </DetailPopup>
      )}

      {modal && (
        <ActionModal item={modal.item} action={modal.action} locations={storageLocs} quarantineLoc={locInfo}
          onClose={() => setModal(null)} onSubmit={doAction} />
      )}
      {showManual && (
        <ManualModal token={token} locations={storageLocs} onClose={() => setShowManual(false)}
          onSaved={() => { setShowManual(false); load(); }} />
      )}
      {rtpItem && (
        <PurchaseReturnCreateModal token={token} quarantineItem={rtpItem} onClose={() => setRtpItem(null)}
          onSaved={(doc) => {
            setRtpItem(null);
            setDetail(null);
            toast.success(`Retur Pembelian ${doc?.rtp_number || ''} dibuat (draf) — kirim/proses dari layar Retur Pembelian (Portal Pengadaan).`, { duration: 8000 });
            load();
          }} />
      )}
    </PageLayout>
  );
}

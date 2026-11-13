/**
 * Form "Buat refund" / "Ubah refund" (Portal Toko › Komplain & Retur › Refund & nota kredit).
 *
 * 14 Nov 2026 — disamakan dengan Gudang › Retur Fisik › "Catat retur" (keputusan owner 10 Nov "wajib referensi +
 * tautkan"): nomor pesanan TIDAK lagi diketik bebas. Staf mencari pesanan marketplace yang sudah diimpor (no. pesanan
 * atau resi); toko, platform, barang, qty maksimum, dan harga terisi dari pesanan. Staf memilih barang yang kembali,
 * qty retur, jenis refund, dan alasan. Baris pesanan yang belum tertaut / baru tertaut model meminta varian master;
 * pilihan itu disimpan server ke Jembatan SKU (jalur resmi), jadi pesanan lain dengan SKU + variasi yang sama ikut
 * tertaut. Pesanan tidak ketemu → arahkan ke Impor Data (bukan ketik bebas).
 * API: GET /api/marketing/returns/order-lookup · POST /api/marketing/returns · PUT /api/marketing/returns/{id}.
 */
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Search, Warehouse, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import DatePicker from '@/components/ui/date-picker';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { BarisDetail } from '@/components/ui/detail-popup';
import { todayWIB } from '@/lib/waktu';
import { formatDateID } from '@/lib/format';
import { Notice } from '../moduleAtoms';
import { VariantSelect } from '../masters/MasterSelects';

const API = process.env.REACT_APP_BACKEND_URL;

export const REFUND_TYPE = { full_refund: 'Refund penuh', partial_refund: 'Refund sebagian', exchange: 'Tukar barang', no_refund: 'Tanpa refund' };
// Tukar barang / tanpa refund tidak punya nominal refund (No.14a).
const NO_MONEY_REFUND = ['exchange', 'no_refund'];
const ORDER_STATUS = {
  new: 'Baru', paid: 'Dibayar', packed: 'Dikemas', shipped: 'Dikirim', delivered: 'Diterima pembeli',
  completed: 'Selesai', cancelled: 'Dibatalkan', returned: 'Dikembalikan',
};
const NAMA_PLATFORM = { shopee: 'Shopee', tiktok: 'TikTok', tiktok_shop: 'TikTok', tiktokshop: 'TikTok', tokopedia: 'Tokopedia', lazada: 'Lazada' };
const labelPlatform = (p) => NAMA_PLATFORM[String(p || '').toLowerCase()] || (p ? String(p).replace(/^./, (x) => x.toUpperCase()) : '');
const rp = (n) => `Rp ${(Number(n) || 0).toLocaleString('id-ID')}`;
const kalimat = (t) => String(t || '').split(' ').map((w, i) => (i === 0 || /^[A-Z0-9]{2,4}$/.test(w) ? w : w.toLowerCase())).join(' ');
const barisLabel = (it) => [it.product_name || it.sku || `Barang ${it.line}`, it.variation].filter(Boolean).join(' · ');
const labelPesanan = (o) => [
  o.order_id, o.account_name, labelPlatform(o.platform), o.customer_name, `${(o.items || []).length} barang`,
  (o.active_refunds || []).length ? 'sudah ada refund' : '',
].filter(Boolean).join(' · ');
const tglPendek = (v) => (v ? (formatDateID(String(v).slice(0, 10)) || String(v).slice(0, 10)) : '');
const persen = (k) => `${Math.round((Number(k) || 0) * 100)}%`;

const KOSONG = {
  date: '', qty: '', item_condition: 'Baik', reason: 'ukuran_salah', reason_detail: '', refund_type: 'full_refund',
  refund_amount: '', notes: '', variant_id: '', price: '',
};

function dariRetur(r) {
  return {
    ...KOSONG, date: r.date || '', qty: r.qty || 1, item_condition: r.item_condition || 'Baik', reason: r.reason,
    reason_detail: r.reason_detail || '', refund_type: r.refund_type || 'full_refund',
    refund_amount: r.refund_amount ?? '', notes: r.notes || '',
  };
}

export default function FormRefundPesanan({ editTarget, authH, reasons = [], onClose, onSaved, onOpenExisting, onNavigate }) {
  const ubah = !!editTarget;
  const [form, setForm] = useState(() => (ubah ? dariRetur(editTarget) : { ...KOSONG, date: todayWIB() }));
  // true = staf sudah mengetik nominal refund sendiri (usulan harga × qty berhenti mengikuti).
  const [refundTouched, setRefundTouched] = useState(ubah);
  const [cari, setCari] = useState('');
  const [mencari, setMencari] = useState(false);
  const [hasil, setHasil] = useState(null);          // null = belum mencari
  const [orderId, setOrderId] = useState('');
  const [line, setLine] = useState('');
  const [semuaVarian, setSemuaVarian] = useState(false);
  const [sudahAda, setSudahAda] = useState([]);      // refund aktif yang dilaporkan server (409)
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');

  const pesanan = (hasil || []).find((o) => o.id === orderId) || null;
  const items = pesanan?.items || [];
  const baris = items.length === 1 ? items[0] : (items.find((it) => String(it.line) === String(line)) || null);
  const kunciBaris = baris ? `${orderId}:${baris.line}` : '';
  const penghalang = sudahAda.length ? sudahAda : (baris?.refund_by || []);
  const perluVarian = !!baris && baris.link_level !== 'varian';
  const harga = ubah ? (Number(editTarget.price) || 0) : (baris?.unit_price || Number(form.price) || 0);
  const qtyMaks = ubah ? null : (baris?.quantity || null);
  const qtyNilai = form.qty === '' ? (baris?.quantity || 1) : form.qty;
  const refundNoMoney = NO_MONEY_REFUND.includes(form.refund_type);
  const usulanRefund = harga * Math.max(1, Number(qtyNilai) || 1);
  const refundShown = refundNoMoney ? 0 : (form.refund_type === 'full_refund' && !refundTouched ? usulanRefund : form.refund_amount);

  // Barang berganti → varian awal = usulan pasti server (bila ada); pemilih varian mulai dari model barisnya.
  useEffect(() => {
    if (ubah || !baris) return;
    setForm((f) => ({ ...f, qty: '', variant_id: baris.link_level !== 'varian' ? (baris.usulan?.variant_id || '') : '' }));
    setSemuaVarian(!baris.model_id);
    setSudahAda([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kunciBaris]);

  const pilihPesanan = (id) => { setOrderId(id); setLine(''); setSudahAda([]); setGalat(''); };

  const cariPesanan = async () => {
    const q = cari.trim();
    if (q.length < 3) { setGalat('Ketik minimal 3 huruf/angka no. pesanan atau no. resi.'); return; }
    setMencari(true); setGalat('');
    try {
      const res = await axios.get(`${API}/api/marketing/returns/order-lookup`, { headers: authH, params: { q } });
      const rows = Array.isArray(res.data?.data) ? res.data.data : [];
      setHasil(rows);
      pilihPesanan(rows.length === 1 ? rows[0].id : '');
    } catch (e) { setGalat(e.response?.data?.detail || e.message); }
    finally { setMencari(false); }
  };

  const simpan = async () => {
    setGalat('');
    if (!ubah) {
      if (!pesanan) { setGalat('Pilih pesanan yang direfund — cari lewat no. pesanan atau no. resi.'); return; }
      if (!baris) { setGalat('Pilih barang yang kembali dari daftar barang pesanan.'); return; }
      if (penghalang.length) { setGalat('Barang ini sudah punya refund — buka refund yang ada.'); return; }
      if (perluVarian && !form.variant_id) { setGalat('Pilih varian master (warna & ukuran) barang yang kembali.'); return; }
    }
    if (!form.reason_detail.trim()) { setGalat('Rincian alasan wajib diisi.'); return; }
    let refundAmount = null;
    if (!refundNoMoney) {
      if (refundShown === '' || refundShown === null || refundShown === undefined || Number.isNaN(Number(refundShown))) {
        setGalat('Isi nominal refund aktual (Rp) sesuai keputusan platform.'); return;
      }
      if (Number(refundShown) < 0) { setGalat('Nominal refund tidak boleh negatif.'); return; }
      refundAmount = Number(refundShown);
    }
    const isian = {
      date: form.date, qty: Number(qtyNilai) || 1, item_condition: form.item_condition, reason: form.reason,
      reason_detail: form.reason_detail, refund_type: form.refund_type, refund_amount: refundAmount, notes: form.notes,
    };
    setSaving(true);
    try {
      if (ubah) {
        const res = await axios.put(`${API}/api/marketing/returns/${editTarget.id}`, isian, { headers: authH });
        onSaved(res.data, true);
      } else {
        const res = await axios.post(`${API}/api/marketing/returns`, {
          ...isian, order_doc_id: pesanan.id, order_line: baris.line,
          variant_id: perluVarian ? form.variant_id : undefined,
          price: baris.unit_price ? undefined : Number(form.price || 0),
        }, { headers: authH });
        onSaved(res.data, false);
      }
    } catch (e) {
      const d = e.response?.data?.detail;
      if (e.response?.status === 409 && Array.isArray(d?.existing)) setSudahAda(d.existing);
      setGalat((d && typeof d === 'object' ? d.message : d) || e.message);
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" onSimpan={simpan} menyimpan={saving} galat={galat}
      judul={ubah ? 'Ubah refund' : 'Buat refund'} testId="return-form"
      labelSimpan={ubah ? 'Simpan' : 'Buat refund'} bisaSimpan={ubah || !penghalang.length}
      keterangan={ubah ? undefined : 'Pilih pesanan yang sudah diimpor. Setelah disimpan, retur fisik di Gudang dibuat otomatis untuk pesanan dan barang yang sama (menunggu paket); stok belum bergerak.'}>
      {ubah ? (
        <>
          <dl className="grid gap-x-6 sm:grid-cols-2" data-testid="return-edit-info">
            <BarisDetail label="No. pesanan">{editTarget.order_id || '—'}</BarisDetail>
            <BarisDetail label="Toko">{[editTarget.account_name, labelPlatform(editTarget.platform)].filter(Boolean).join(' · ') || '—'}</BarisDetail>
            <BarisDetail label="Barang">{editTarget.product || '—'}</BarisDetail>
            <BarisDetail label="Harga satuan">{rp(editTarget.price)}</BarisDetail>
          </dl>
          {!editTarget.order_doc_id && (
            <Notice tone="info" testId="return-edit-legacy">
              Refund lama ini dibuat sebelum pesanan wajib dipilih, jadi pesanan dan barangnya tidak bisa diubah di sini.
              Bila salah, hapus lalu buat refund baru dari pesanannya.
            </Notice>
          )}
        </>
      ) : (
        <>
          <Isian label="Cari pesanan" wajib htmlFor="refund-cari" petunjuk="Ketik no. pesanan atau no. resi (minimal 3 huruf/angka), lalu tekan Cari.">
            <div className="flex gap-2">
              <Input id="refund-cari" value={cari} onChange={(e) => setCari(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); cariPesanan(); } }}
                placeholder="No. pesanan atau no. resi" data-testid="return-order-search" />
              <Button type="button" variant="outline" onClick={cariPesanan} disabled={mencari} data-testid="return-order-search-btn">
                <Search />{mencari ? 'Mencari…' : 'Cari'}
              </Button>
            </div>
          </Isian>
          {hasil && hasil.length === 0 && (
            <Notice tone="warning" testId="return-order-none" title="Pesanan tidak ditemukan"
              action={typeof onNavigate === 'function' && (
                <Button type="button" size="sm" variant="outline" onClick={() => { onClose(); onNavigate('marketing-import', {}); }}
                  data-testid="return-goto-import"><Upload />Buka Impor Data</Button>
              )}>
              Refund hanya bisa dibuat untuk pesanan yang sudah ada di sistem. Periksa nomornya, atau impor dulu berkas
              pesanan dari Seller Center di Impor Data, lalu cari lagi.
            </Notice>
          )}
          {hasil && hasil.length > 0 && (
            <Isian label="Pesanan" wajib htmlFor="refund-order-pick">
              <SmartNativeSelect id="refund-order-pick" value={orderId} onChange={(e) => pilihPesanan(e.target.value)} data-testid="return-order-pick">
                <option value="">{`Pilih pesanan (${hasil.length} ditemukan)`}</option>
                {hasil.map((o) => <option key={o.id} value={o.id}>{labelPesanan(o)}</option>)}
              </SmartNativeSelect>
            </Isian>
          )}
          {pesanan && (
            <dl className="grid gap-x-6 sm:grid-cols-2" data-testid="return-order-info">
              <BarisDetail label="Toko">{[pesanan.account_name, labelPlatform(pesanan.platform)].filter(Boolean).join(' · ') || '—'}</BarisDetail>
              <BarisDetail label="No. resi">{pesanan.tracking_number || '—'}</BarisDetail>
              <BarisDetail label="Pembeli">{pesanan.customer_name || '—'}</BarisDetail>
              <BarisDetail label="Status pesanan">
                {ORDER_STATUS[pesanan.status] || pesanan.status || '—'}{pesanan.order_date ? ` · ${tglPendek(pesanan.order_date)}` : ''}
              </BarisDetail>
              {items.length === 1 && (
                <BarisDetail label="Barang di pesanan">{barisLabel(items[0])} · {items[0].quantity || '?'} pcs · {rp(items[0].unit_price)}</BarisDetail>
              )}
            </dl>
          )}
          {pesanan && items.length > 1 && (
            <Isian label="Barang yang kembali" wajib htmlFor="refund-line" petunjuk={`Pesanan ini berisi ${items.length} barang — pilih yang direfund.`}>
              <SmartNativeSelect id="refund-line" value={String(line)} onChange={(e) => setLine(e.target.value)} data-testid="return-order-line">
                <option value="">Pilih barang</option>
                {items.map((it) => (
                  <option key={it.line} value={String(it.line)}>
                    {`${barisLabel(it)} · ${it.quantity || '?'} pcs · ${rp(it.unit_price)}${(it.refund_by || []).length ? ' · sudah direfund' : ''}`}
                  </option>
                ))}
              </SmartNativeSelect>
            </Isian>
          )}
          {penghalang.length > 0 && (
            <Notice tone="warning" testId="return-sudah-ada"
              title={`Barang ini sudah punya refund: ${penghalang.map((r) => `${tglPendek(r.date) || '—'} (${r.status_label || r.status})`).join(', ')}`}
              action={typeof onOpenExisting === 'function' && (
                <div className="flex flex-wrap gap-2">
                  {penghalang.map((r) => (
                    <Button key={r.id} type="button" size="sm" variant="outline" onClick={() => onOpenExisting(r.id)} data-testid={`return-buka-${r.id}`}>
                      Buka refund {tglPendek(r.date)}
                    </Button>
                  ))}
                </div>
              )}>
              Satu barang tidak boleh direfund dua kali. Buka refund yang ada untuk mengubah atau melanjutkannya.
            </Notice>
          )}
          {baris && !penghalang.length && (perluVarian ? (
            <Isian label="Varian master yang kembali" wajib
              petunjuk={`${baris.link_level === 'model'
                ? `Pesanan ini baru tertaut ke model ${baris.model_code || ''} — warna & ukurannya belum pasti.`
                : 'Barang di baris pesanan ini belum tertaut ke master.'} Pilihan Anda disimpan ke Jembatan SKU, jadi pesanan lain dengan SKU dan variasi “${baris.variation || '-'}” ikut tertaut.`}>
              <VariantSelect value={form.variant_id} onChange={(v) => setForm((f) => ({ ...f, variant_id: v }))}
                modelId={semuaVarian ? undefined : baris.model_id} label={null} testId="return-variant-select" />
              {baris.usulan?.variant_id && (
                <p className="text-xs text-muted-foreground" data-testid="return-variant-usulan">
                  Usulan sistem: <span className="font-medium text-foreground">{baris.usulan.label}</span>
                  {` (${persen(baris.usulan.keyakinan)} yakin — ${(baris.usulan.alasan || []).join('; ')}). Periksa sebelum menyimpan.`}
                </p>
              )}
              {baris.model_id && (
                <Button type="button" variant="link" size="sm" className="h-auto self-start px-0" onClick={() => setSemuaVarian((s) => !s)}
                  data-testid="return-variant-scope">
                  {semuaVarian ? `Tampilkan hanya varian model ${baris.model_code || 'ini'}` : 'Bukan model ini? Pilih dari semua varian'}
                </Button>
              )}
            </Isian>
          ) : (
            <dl data-testid="return-line-material">
              <BarisDetail label="Barang master (dari pesanan)">{[baris.material_code, baris.material_name].filter(Boolean).join(' · ') || '—'}</BarisDetail>
            </dl>
          ))}
          {baris && !penghalang.length && !baris.unit_price && (
            <Isian label="Harga satuan" wajib petunjuk="Pesanan ini tidak membawa harga barang — isi harga jual yang dibayar pembeli.">
              <MoneyInput value={form.price} onChange={(e) => setForm((f) => ({ ...f, price: e.target.value }))} data-testid="return-price-input" />
            </Isian>
          )}
        </>
      )}

      {(ubah || (baris && !penghalang.length)) && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label={qtyMaks ? `Qty retur (di pesanan ${qtyMaks} pcs)` : 'Qty retur'} wajib htmlFor="return-qty">
              <Input id="return-qty" type="number" min={1} max={qtyMaks || undefined} value={qtyNilai}
                onChange={(e) => setForm((f) => ({ ...f, qty: e.target.value === '' ? '' : Math.max(1, parseInt(e.target.value, 10) || 1) }))}
                data-testid="return-qty-input" />
            </Isian>
            <Isian label="Kondisi barang" wajib htmlFor="return-condition">
              <SmartNativeSelect id="return-condition" value={form.item_condition || 'Baik'} searchable={false}
                onChange={(e) => setForm((f) => ({ ...f, item_condition: e.target.value }))} data-testid="return-condition-select">
                <option value="Baik">Baik (laporan pembeli)</option>
                <option value="Rusak">Rusak (laporan pembeli)</option>
              </SmartNativeSelect>
            </Isian>
            <Isian label="Tanggal refund">
              <DatePicker value={form.date || ''} onChange={(v) => setForm((f) => ({ ...f, date: v }))} testId="return-date" />
            </Isian>
            <Isian label="Jenis refund" htmlFor="return-refund-type">
              <SmartNativeSelect id="return-refund-type" value={form.refund_type} searchable={false}
                onChange={(e) => setForm((f) => ({ ...f, refund_type: e.target.value }))} data-testid="return-refund-type-select">
                {Object.entries(REFUND_TYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </SmartNativeSelect>
            </Isian>
          </div>
          {!ubah && baris?.unit_price > 0 && (
            <dl><BarisDetail label="Harga satuan (dari pesanan)"><span className="tabular-nums">{rp(harga)}</span></BarisDetail></dl>
          )}
          {/* 2026-11-02 (No.14a) — NOMINAL REFUND AKTUAL (dulu refund sebagian dipatok 70% harga). */}
          {!refundNoMoney && (
            <Isian label="Nominal refund aktual (Rp)" wajib
              petunjuk={form.refund_type === 'full_refund'
                ? `Usulan awal = harga × qty (${rp(usulanRefund)}). Ubah bila platform mengembalikan nominal lain.`
                : 'Isi nominal yang benar-benar dikembalikan platform ke pembeli.'}>
              <MoneyInput value={refundShown}
                onChange={(e) => { setRefundTouched(true); setForm((f) => ({ ...f, refund_amount: e.target.value })); }}
                placeholder={form.refund_type === 'partial_refund' ? 'isi sesuai keputusan platform' : ''}
                data-testid="return-refund-amount-input" />
              {refundTouched && form.refund_type === 'full_refund' && (
                <Button type="button" variant="link" size="sm" className="h-auto self-start px-0"
                  onClick={() => { setRefundTouched(false); setForm((f) => ({ ...f, refund_amount: '' })); }}>
                  Pakai harga × qty
                </Button>
              )}
            </Isian>
          )}
          <Notice tone="info" icon={Warehouse}>
            Gudang menerima paket &amp; mengisi qty aktual, memeriksa kondisinya, lalu memutuskan (terima → stok jual,
            rusak → karantina, tolak → dikembalikan ke pembeli, dibuang). Omzet setelah retur baru berkurang setelah keputusan itu.
          </Notice>
          <Isian label="Alasan" htmlFor="return-reason">
            <SmartNativeSelect id="return-reason" value={form.reason} onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}>
              {reasons.map((r) => <option key={r.value} value={r.value}>{kalimat(r.label)}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Rincian alasan" wajib htmlFor="return-reason-detail">
            <Textarea id="return-reason-detail" value={form.reason_detail} rows={2} placeholder="Rincian alasan retur"
              onChange={(e) => setForm((f) => ({ ...f, reason_detail: e.target.value }))} data-testid="return-reason-detail" />
          </Isian>
          <Isian label="Catatan" htmlFor="return-notes">
            <Textarea id="return-notes" value={form.notes} rows={2} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} />
          </Isian>
        </>
      )}
    </FormPopup>
  );
}

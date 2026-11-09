import { useState, useEffect, useCallback, useMemo } from 'react';
import { Printer, Search, Trash2, RefreshCw, AlertTriangle, Plus } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Isian } from '@/components/ui/form-popup';
import { formatDateID, formatDateTimeID } from '@/lib/format';
import { apiGet, apiFetch } from '../../lib/api';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';

// FASE H-3 (2026-08-16) — "Buat Barcode".
// Kenapa layar ini ada: endpoint label bahan & barang jadi sudah lama tersedia
// dengan NOL pemanggil UI, jadi dari sudut pandang pemakai barcode gudang tidak
// bisa dicetak sama sekali. Nilai barcode SELALU kode master — tidak ada kotak
// untuk mengetik kode bebas, karena label yang kodenya dikarang akan discan
// menjadi item yang tidak ada di sistem (aturan F14).
//
// Standar UI/UX v2 (8 Nov 2026): PageLayout (kepala ikon besar dihapus), tombol jenis buatan → pil penyaring,
// tiga `<table>` → TabelData (kartu ringkas di HP; dulu teks bertumpuk di 390 px) masing-masing dengan unduh
// Excel/CSV, kotak pesan berwarna → Notice, checkbox/isian polos → komponen standar. Alur cetak tidak berubah.
//
// 10 Nov 2026 (permintaan owner: "pilih dari master tapi tidak bisa search dan tidak bisa filter … harusnya bisa
// juga dari pembelian misal kain roll"):
//   · Kotak cari dipindah ke kepala kartu "Pilih dari master" (dulu di baris penyaring halaman, jauh dari
//     daftarnya) + penyaring Kategori & Warna dari master; daftar dimuat bertahap ("Tampilkan lebih banyak"),
//     tidak lagi berhenti di 60; "Tambah semua yang tampil".
//   · Sumber otomatis kedua "Dari penerimaan barang": bahan non-kain → label bahan (lembar = qty diterima bila
//     satuannya hitungan), kain → label ROLL per gulungan dari penerimaan itu. Riwayat: sumber "Dari pembelian".

const MAX_LABELS = 500;
const PER_MUAT = 60;

const KINDS = [
  { key: 'material', label: 'Bahan & aksesoris' },
  { key: 'fg', label: 'Barang jadi' },
];
const JENIS_USAHA = { internal: 'Produksi internal', maklon: 'Maklon', customer_po: 'Customer PO' };
const jenisUsaha = (v) => JENIS_USAHA[v] || (v ? 'Lainnya' : '—');
const angka = (n) => Number(n || 0).toLocaleString('id-ID');
const angkaDesimal = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 });

// Kunci baris daftar cetak: roll per gulungan, baris tak tertaut per barisnya, bahan/barang jadi per kode.
const kunciBaris = (r) => r.key || r.code;
const varianBaris = (r) => (r.label_kind === 'roll'
  ? [r.color, r.color_lot ? `Lot ${r.color_lot}` : '', r.qty_total != null ? `${angkaDesimal(r.qty_total)} ${r.unit || ''}`.trim() : '']
    .filter(Boolean).join(' · ') || '—'
  : [r.color, r.size].filter(Boolean).join(' · ') || '—');
const labelPenerimaan = (g) => [
  g.receipt_number, g.supplier_name || 'Tanpa pemasok', g.po_number || 'Tanpa PO',
  formatDateID(g.received_at, { fallback: '' }),
].filter(Boolean).join(' · ');

const sumberRiwayat = (h) => {
  if (h.source === 'pembelian') return h.receipt_number ? `Dari pembelian · ${h.receipt_number}` : 'Dari pembelian';
  if (h.source === 'produksi') return 'Dari produksi';
  return 'Manual';
};
const jenisRiwayat = (h) => {
  if (h.kind === 'fg') return h.size === 'hangtag' ? 'Barang jadi · hangtag' : 'Barang jadi';
  if (h.roll_labels > 0) return h.roll_labels >= h.total_labels ? 'Roll kain' : 'Bahan & roll kain';
  return 'Bahan';
};

export default function WMSBarcodeModule() {
  const [kind, setKind] = useState('material');
  const [q, setQ] = useState('');
  const [cari, setCari] = useState('');
  const [kategori, setKategori] = useState('');
  const [warna, setWarna] = useState('');
  const [items, setItems] = useState([]);
  const [itemsMeta, setItemsMeta] = useState({ total: 0, hasMore: false });
  const [pilihan, setPilihan] = useState({ categories: [], colors: [] });
  const [loadingItems, setLoadingItems] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [cart, setCart] = useState([]);
  const [includeStock, setIncludeStock] = useState(true);

  // 2026-11-02 (keputusan owner): ukuran label barang jadi — standar 100×70 / hangtag 70×40

  const [fgSize, setFgSize] = useState('standard');
  const [note, setNote] = useState('');
  const [pos, setPos] = useState([]);
  const [poId, setPoId] = useState('');
  const [poInfo, setPoInfo] = useState(null);
  const [receipts, setReceipts] = useState([]);
  const [receiptId, setReceiptId] = useState('');
  const [receiptInfo, setReceiptInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [okMsg, setOkMsg] = useState('');
  const [history, setHistory] = useState([]);

  // Ketikan pencarian diteruskan setelah jeda singkat (Enter langsung mencari).
  useEffect(() => {
    const t = setTimeout(() => setQ(cari.trim()), 300);
    return () => clearTimeout(t);
  }, [cari]);

  const itemsUrl = useCallback((skip) => (
    `/wms/barcode/items?kind=${kind}&q=${encodeURIComponent(q)}&category=${encodeURIComponent(kategori)}`
    + `&color=${encodeURIComponent(warna)}&skip=${skip}&limit=${PER_MUAT}`
  ), [kind, q, kategori, warna]);

  const loadItems = useCallback(async () => {
    setLoadingItems(true);
    try {
      const d = await apiGet(itemsUrl(0));
      setItems(d.items || []);
      setItemsMeta({ total: d.total || 0, hasMore: !!d.has_more });
      setPilihan({ categories: d.categories || [], colors: d.colors || [] });
    } catch (e) { setError(e.message); } finally { setLoadingItems(false); }
  }, [itemsUrl]);

  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const d = await apiGet(itemsUrl(items.length));
      setItems(prev => {
        const ada = new Set(prev.map(it => it.id));
        return [...prev, ...(d.items || []).filter(it => !ada.has(it.id))];
      });
      setItemsMeta({ total: d.total || 0, hasMore: !!d.has_more });
    } catch (e) { setError(e.message); } finally { setLoadingMore(false); }
  };

  const loadHistory = useCallback(async () => {
    try { setHistory(await apiGet('/wms/barcode/history?limit=15')); } catch { /* riwayat opsional */ }
  }, []);

  useEffect(() => { loadItems(); }, [loadItems]);
  useEffect(() => { loadHistory(); }, [loadHistory]);
  useEffect(() => {
    // 100 PO produksi terbaru (batas maksimum API; dulu 40 → PO lebih lama tidak bisa dipilih)
    apiGet('/wms/barcode/production-options?limit=100').then(setPos).catch(() => setPos([]));
    // 100 penerimaan barang terbaru yang sudah diterima (stoknya sudah masuk)
    apiGet('/wms/barcode/receipt-options?limit=100').then(setReceipts).catch(() => setReceipts([]));
  }, []);

  const totalLabels = useMemo(
    () => cart.reduce((s, r) => s + (Number(r.copies) || 0), 0), [cart]);
  const unlinked = useMemo(() => cart.filter(r => r.master_linked === false), [cart]);
  const bisaDicetak = useMemo(() => cart.filter(r => r.master_linked !== false), [cart]);
  const overLimit = totalLabels > MAX_LABELS;

  // Ganti jenis = pilihan kategori/warna jenis lama tidak berlaku lagi.
  const pilihJenis = (id) => {
    if (id === kind) return;
    setKind(id); setKategori(''); setWarna('');
  };

  const barisDariMaster = (it) => ({
    key: it.code, label_kind: kind, material_id: it.id, code: it.code, name: it.name, size: it.size,
    color: it.color, copies: 1, master_linked: true,
  });
  const samaKode = (r, code) => r.label_kind !== 'roll' && r.master_linked !== false && r.code === code;

  const addItem = (it) => {
    setOkMsg('');
    setCart(prev => {
      const found = prev.find(r => samaKode(r, it.code));
      if (found) return prev.map(r => (r === found ? { ...r, copies: (Number(r.copies) || 0) + 1 } : r));
      return [...prev, barisDariMaster(it)];
    });
  };

  const addAllShown = () => {
    const baru = items.filter(it => !cart.some(r => samaKode(r, it.code)));
    setCart(prev => [...prev, ...baru.map(barisDariMaster)]);
    setError('');
    setOkMsg(baru.length ? `${angka(baru.length)} item ditambahkan ke daftar cetak (1 lembar per item)` : 'Semua item yang tampil sudah ada di daftar cetak');
  };

  const setCopies = (key, val) => setCart(prev => prev.map(
    r => kunciBaris(r) === key ? { ...r, copies: val === '' ? '' : Math.max(1, Math.min(200, Number(val) || 1)) } : r));
  const removeRow = (key) => setCart(prev => prev.filter(r => kunciBaris(r) !== key));

  const loadFromPO = async () => {
    if (!poId) return;
    setError(''); setOkMsg(''); setBusy(true);
    try {
      const d = await apiGet(`/wms/barcode/from-production?po_id=${encodeURIComponent(poId)}`);
      pilihJenis('fg');
      setPoInfo(d);
      setReceiptInfo(null);
      setCart((d.rows || []).map((r, i) => ({
        ...r, key: `po-${i}`, label_kind: 'fg', copies: Math.max(1, Math.min(200, r.copies || 1)),
      })));
      setOkMsg(`${(d.rows || []).length} artikel dari ${d.po_number} dimuat · ${d.total_copies} label mengikuti jumlah produksi`);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const loadFromReceipt = async () => {
    if (!receiptId) return;
    setError(''); setOkMsg(''); setBusy(true);
    try {
      const d = await apiGet(`/wms/barcode/from-receipt?receipt_id=${encodeURIComponent(receiptId)}`);
      pilihJenis('material');
      setPoInfo(null);
      setReceiptInfo(d);
      setCart((d.rows || []).map((r, i) => ({
        ...r,
        key: r.label_kind === 'roll' ? `roll:${r.roll_id || r.code}` : (r.master_linked === false ? `gr-${i}` : r.code),
        copies: Math.max(1, Math.min(200, r.copies || 1)),
      })));
      setOkMsg(`${angka(d.material_count)} bahan dan ${angka(d.roll_count)} roll kain dari ${d.receipt_number} dimuat · ${angka(d.total_copies)} label`);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const printPdf = async () => {
    setError(''); setOkMsg(''); setBusy(true);
    try {
      const res = await apiFetch('/wms/barcode/batch-pdf', {
        method: 'POST',
        body: JSON.stringify({
          kind,
          rows: bisaDicetak.filter(r => r.label_kind !== 'roll')
            .map(r => ({ id: r.material_id || undefined, code: r.code, copies: Number(r.copies) || 1 })),
          rolls: bisaDicetak.filter(r => r.label_kind === 'roll')
            .map(r => ({ id: r.roll_id || undefined, roll_no: r.code, copies: Number(r.copies) || 1 })),
          include_stock: kind === 'material' ? includeStock : false,

          size: kind === 'fg' ? fgSize : 'standard',
          source: receiptInfo ? 'pembelian' : (poInfo ? 'produksi' : 'manual'),
          po_id: poInfo?.po_id || null,
          receipt_id: receiptInfo?.receipt_id || null,
          note,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setError(typeof err.detail === 'string' ? err.detail : `Gagal mencetak (HTTP ${res.status})`);
        return;
      }
      const jobNo = res.headers.get('X-Barcode-Job') || '';
      const labels = res.headers.get('X-Barcode-Labels') || totalLabels;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `barcode-${kind}-${jobNo || 'batch'}.pdf`;
      a.click();
      // Jangan cabut URL-nya seketika: di mesin lambat unduhan bisa dibatalkan
      // sebelum browser selesai membaca blob-nya.
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      setOkMsg(`${labels} label tercetak ke PDF · nomor cetak ${jobNo}`);
      loadHistory();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const kolomMaster = [
    { kunci: 'code', label: 'Kode', hp: 'judul', isi: (it) => <span className="tabular-nums">{it.code}</span> },
    // Nama dipotong dengan judul lengkap di `title`: dulu nama panjang mendorong kolom Satuan & tombol tambah keluar kartu.
    { kunci: 'name', label: 'Nama', hp: 'keterangan', isi: (it) => (
      <div className="min-w-0">
        <span className="block max-w-[10rem] truncate xl:max-w-[13rem] 2xl:max-w-[18rem]" title={it.name}>{it.name}</span>
        {(it.category || it.color) && (
          <span className="block max-w-[10rem] truncate text-xs text-muted-foreground xl:max-w-[13rem] 2xl:max-w-[18rem]">
            {[it.category, it.color].filter(Boolean).join(' · ')}
          </span>
        )}
      </div>) },
    { kunci: 'unit', label: 'Satuan', hp: false, isi: (it) => <span className="text-muted-foreground">{it.unit}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (it) => (
      <Button size="icon-sm" variant="outline" onClick={() => addItem(it)} title="Tambah ke daftar cetak"
        aria-label={`Tambah ${it.code} ke daftar cetak`} data-testid={`barcode-add-${it.code}`}>
        <Plus />
      </Button>) },
  ];
  const kolomCetak = [
    { kunci: 'code', label: 'Kode', hp: 'judul', isi: (r) => (
      <div data-testid={`barcode-cart-row-${r.code}`}>
        <span className="tabular-nums">{r.code}</span>
        {r.label_kind === 'roll' && <span className="ml-1 text-xs text-muted-foreground">· label roll</span>}
        {r.master_linked === false && (
          <p className="mt-0.5 text-xs text-[hsl(var(--danger-text))]" data-testid={`barcode-unlinked-${r.code}`}>
            {r.reason || 'Belum ada di master barang jadi — labelnya tidak bisa dicetak.'}
          </p>
        )}
      </div>) },
    { kunci: 'name', label: 'Nama', hp: 'keterangan', isi: (r) => <span className="block max-w-[13rem] truncate xl:max-w-[18rem]" title={r.name}>{r.name}</span> },
    { kunci: 'varian', label: 'Varian', hp: false, isi: varianBaris },
    { kunci: 'copies', label: 'Lembar', rata: 'kanan', isi: (r) => (
      <Input type="number" min="1" max="200" value={r.copies} onChange={e => setCopies(kunciBaris(r), e.target.value)}
        className="ml-auto h-8 w-20 text-right" aria-label={`Jumlah lembar ${r.code}`} data-testid={`barcode-copies-${r.code}`} />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button variant="ghost" size="icon-sm" onClick={() => removeRow(kunciBaris(r))} title="Hapus baris" aria-label={`Hapus ${r.code} dari daftar cetak`}
        data-testid={`barcode-remove-${r.code}`}><Trash2 /></Button>) },
  ];
  const kolomRiwayat = [
    { kunci: 'job', label: 'No. cetak', hp: 'judul', isi: (h) => <span className="tabular-nums" data-testid={`barcode-history-${h.job_number}`}>{h.job_number}</span> },
    { kunci: 'kind', label: 'Jenis', hp: false, isi: jenisRiwayat },
    { kunci: 'source', label: 'Sumber', hp: false, isi: sumberRiwayat },
    { kunci: 'items', label: 'Item', hp: false, rata: 'kanan', isi: (h) => <span className="tabular-nums">{angka(h.item_count)}</span> },
    { kunci: 'labels', label: 'Lembar', rata: 'kanan', isi: (h) => <span className="tabular-nums font-medium">{angka(h.total_labels)}</span> },
    { kunci: 'by', label: 'Oleh', hp: false, isi: (h) => h.created_by_name || '—' },
    { kunci: 'at', label: 'Waktu', hp: 'keterangan', isi: (h) => formatDateTimeID(h.created_at) },
  ];

  return (
    <PageLayout testId="wms-barcode-page" title="Buat barcode"
      subtitle="Cetak label barcode bahan, aksesoris, roll kain, dan barang jadi; kodenya selalu diambil dari master."
      filters={
        <FilterChips options={KINDS} value={kind}
          onChange={(id) => { pilihJenis(id); setPoInfo(null); setReceiptInfo(null); }} hideWhenEmpty={false}
          className="w-full sm:w-auto" testId="barcode-tab" ariaLabel="Jenis barang" />
      }
      tools={
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={loadItems} disabled={loadingItems}
          data-testid="barcode-search-btn">
          <RefreshCw className={loadingItems ? 'animate-spin' : ''} />
        </Button>
      }
      summary={
        <GlassCard className="p-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Sumber otomatis 1: PO produksi (barang jadi) */}
            <div className="min-w-0 space-y-2">
              <div className="flex flex-wrap items-end gap-2">
                <Isian label="Otomatis dari PO produksi" className="w-full sm:w-80">
                  <SmartNativeSelect value={poId} onChange={e => setPoId(e.target.value)} className="w-full" data-testid="barcode-po-select">
                    <option value="">{pos.length ? 'Pilih PO produksi' : 'Belum ada PO produksi'}</option>
                    {pos.map(p => (
                      <option key={p.id} value={p.id}>{`${p.po_number} · ${jenisUsaha(p.business_type)} · ${p.total_qty} pcs`}</option>
                    ))}
                  </SmartNativeSelect>
                </Isian>
                <Button variant="outline" onClick={loadFromPO} disabled={!poId || busy} data-testid="barcode-load-po-btn">
                  <Plus />Ambil artikel & jumlahnya
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">Label barang jadi; jumlahnya mengikuti qty PO (100 PO terbaru).</p>
              {poInfo && (
                <p className="text-sm text-muted-foreground" data-testid="barcode-po-info">
                  Sumber: <span className="font-medium text-foreground">{poInfo.po_number}</span> ({jenisUsaha(poInfo.business_type)}) ·
                  {' '}{poInfo.rows?.length || 0} artikel · {poInfo.total_copies} label
                  {poInfo.unlinked_count > 0 && (
                    <span className="text-[hsl(var(--danger-text))]"> · {poInfo.unlinked_count} artikel belum ada di master</span>
                  )}
                </p>
              )}
            </div>

            {/* Sumber otomatis 2: penerimaan barang dari pembelian (bahan + roll kain) */}
            <div className="min-w-0 space-y-2">
              <div className="flex flex-wrap items-end gap-2">
                <Isian label="Otomatis dari penerimaan barang" className="w-full sm:w-80">
                  <SmartNativeSelect value={receiptId} onChange={e => setReceiptId(e.target.value)} className="w-full" data-testid="barcode-receipt-select">
                    <option value="">{receipts.length ? 'Pilih penerimaan barang' : 'Belum ada penerimaan yang diterima'}</option>
                    {receipts.map(g => <option key={g.id} value={g.id}>{labelPenerimaan(g)}</option>)}
                  </SmartNativeSelect>
                </Isian>
                <Button variant="outline" onClick={loadFromReceipt} disabled={!receiptId || busy} data-testid="barcode-load-receipt-btn">
                  <Plus />Ambil barang & jumlahnya
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">Bahan dicetak label bahan, kain dicetak label roll per gulungan (100 penerimaan terbaru).</p>
              {receiptInfo && (
                <p className="text-sm text-muted-foreground" data-testid="barcode-receipt-info">
                  Sumber: <span className="font-medium text-foreground">{receiptInfo.receipt_number}</span>
                  {receiptInfo.supplier_name ? ` (${receiptInfo.supplier_name})` : ''} ·
                  {' '}{angka(receiptInfo.material_count)} bahan · {angka(receiptInfo.roll_count)} roll kain · {angka(receiptInfo.total_copies)} label
                  {receiptInfo.unlinked_count > 0 && (
                    <span className="text-[hsl(var(--danger-text))]"> · {receiptInfo.unlinked_count} baris belum tertaut ke master</span>
                  )}
                  {receiptInfo.skipped?.length > 0 && ` · ${receiptInfo.skipped.length} baris tidak perlu label`}
                </p>
              )}
              {receiptInfo?.message && (
                <Notice tone="warning" icon={AlertTriangle} testId="barcode-receipt-no-roll">
                  {receiptInfo.message}
                  {receiptInfo.fabric_without_rolls?.length > 0 && (
                    <span className="mt-1 block text-xs">
                      {receiptInfo.fabric_without_rolls.map(f => `${f.material_code} ${f.material_name} (${angkaDesimal(f.accepted_qty)} ${f.unit})`).join(' · ')}
                    </span>
                  )}
                </Notice>
              )}
            </div>
          </div>
        </GlassCard>
      }>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Pemilih dari master */}
        <GlassCard className="min-w-0 space-y-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-base font-semibold text-foreground">Pilih dari master</p>
              <p className="text-xs text-muted-foreground" data-testid="barcode-items-meta">
                Menampilkan {angka(items.length)} dari {angka(itemsMeta.total)} item
              </p>
            </div>
            <TombolUnduh namaBerkas={`master-barcode-${kind}`} namaLembar="Master" baris={items} testId="barcode-items-unduh"
              kolom={[
                { label: 'Kode', nilai: (it) => it.code }, { label: 'Nama', nilai: (it) => it.name },
                { label: 'Kategori', nilai: (it) => it.category || '' },
                { label: 'Satuan', nilai: (it) => it.unit || '' }, { label: 'Warna', nilai: (it) => it.color || '' },
                { label: 'Ukuran', nilai: (it) => it.size || '' },
              ]} />
          </div>
          {/* Cari & saring tepat di atas daftarnya (dulu kotak cari di baris penyaring halaman, tanpa penyaring). */}
          <div className="flex flex-wrap items-center gap-2" data-testid="barcode-items-filters">
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={cari} onChange={e => setCari(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { if (cari.trim() === q) loadItems(); else setQ(cari.trim()); } }}
                placeholder="Cari kode atau nama item" className="pl-8" aria-label="Cari kode atau nama item"
                data-testid="barcode-search-input" />
            </div>
            <SmartNativeSelect value={kategori} onChange={e => { setKategori(e.target.value); setWarna(''); }}
              aria-label="Kategori" wrapperClassName="w-full sm:w-52" className="w-full" data-testid="barcode-category-filter">
              <option value="">Semua kategori</option>
              {pilihan.categories.map(c => <option key={c.value} value={c.value}>{`${c.label} (${angka(c.count)})`}</option>)}
            </SmartNativeSelect>
            {pilihan.colors.length > 0 && (
              <SmartNativeSelect value={warna} onChange={e => setWarna(e.target.value)}
                aria-label="Warna" wrapperClassName="w-full sm:w-44" className="w-full" data-testid="barcode-color-filter">
                <option value="">Semua warna</option>
                {pilihan.colors.map(c => <option key={c.value} value={c.value}>{`${c.label} (${angka(c.count)})`}</option>)}
              </SmartNativeSelect>
            )}
          </div>
          <div className="max-h-[28rem] overflow-y-auto">
            <TabelData kolom={kolomMaster} baris={items} testId="barcode-items-table"
              kosong={<p className="py-6 text-center text-sm text-muted-foreground" data-testid="barcode-items-empty">Tidak ada item yang cocok.</p>} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button variant="outline" size="sm" onClick={addAllShown} disabled={items.length === 0} data-testid="barcode-add-all-btn">
              <Plus />Tambah semua yang tampil ({angka(items.length)})
            </Button>
            {itemsMeta.hasMore && (
              <Button variant="outline" size="sm" onClick={loadMore} disabled={loadingMore} data-testid="barcode-load-more-btn">
                {loadingMore ? 'Memuat…' : `Tampilkan lebih banyak (sisa ${angka(itemsMeta.total - items.length)})`}
              </Button>
            )}
          </div>
        </GlassCard>

        {/* Daftar cetak */}
        <GlassCard className="min-w-0 space-y-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-base font-semibold text-foreground">Daftar cetak</p>
              <span data-testid="barcode-total-labels">
                <StatusBadge status="total" tone={overLimit ? 'danger' : 'default'} label={`${angka(totalLabels)} label · ${cart.length} item`} />
              </span>
            </div>
            <TombolUnduh namaBerkas="daftar-cetak-barcode" namaLembar="Daftar cetak" baris={cart} testId="barcode-cart-unduh"
              kolom={[
                { label: 'Kode', nilai: (r) => r.code }, { label: 'Nama', nilai: (r) => r.name },
                { label: 'Jenis label', nilai: (r) => (r.label_kind === 'roll' ? 'Roll kain' : (r.label_kind === 'fg' ? 'Barang jadi' : 'Bahan')) },
                { label: 'Varian', nilai: varianBaris },
                { label: 'Lembar', nilai: (r) => Number(r.copies || 0) },
                { label: 'Ada di master', nilai: (r) => (r.master_linked === false ? 'Tidak' : 'Ya') },
              ]} />
          </div>

          <TabelData kolom={kolomCetak} baris={cart} kunci={kunciBaris} testId="barcode-cart-table"
            kosong={
              <div data-testid="barcode-cart-empty">
                <EmptyState className="py-6" title="Belum ada item dipilih" description="Pilih dari master, atau ambil otomatis dari PO produksi atau penerimaan barang." />
              </div>
            } />

          {kind === 'fg' && (
            <Isian label="Ukuran label">
              <SmartNativeSelect value={fgSize} onChange={e => setFgSize(e.target.value)} data-testid="barcode-fg-size"
                searchable={false} className="w-full" wrapperClassName="w-full sm:w-72">
                <option value="standard">Label standar 100×70 mm</option>
                <option value="hangtag">Hangtag kecil 70×40 mm</option>
              </SmartNativeSelect>
            </Isian>
          )}
          {kind === 'material' && (
            <label className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
              <Checkbox checked={includeStock} onCheckedChange={(v) => setIncludeStock(!!v)} data-testid="barcode-include-stock" />
              Cetak stok & lokasi di label bahan
            </label>
          )}

          <Isian label="Catatan cetak" petunjuk="Opsional" htmlFor="barcode-note">
            <Input id="barcode-note" value={note} onChange={e => setNote(e.target.value)}
              placeholder="mis. label rak B, giliran pagi" data-testid="barcode-note-input" />
          </Isian>

          {unlinked.length > 0 && (
            <Notice tone="danger" icon={AlertTriangle} testId="barcode-unlinked-warning">
              {unlinked.length} baris belum tertaut ke master, jadi labelnya tidak dicetak. Tautkan dulu barangnya ke
              master — mencetak barcode dengan kode yang tidak dikenal sistem hanya memindahkan masalahnya ke rak.
            </Notice>
          )}
          {overLimit && (
            <Notice tone="danger" testId="barcode-limit-warning">
              Total {angka(totalLabels)} label melebihi batas {MAX_LABELS} lembar per cetak. Kurangi jumlahnya atau cetak beberapa kali.
            </Notice>
          )}
          {error && <Notice tone="danger" testId="barcode-error">{error}</Notice>}
          {okMsg && <Notice tone="success" testId="barcode-success">{okMsg}</Notice>}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button variant="outline" onClick={() => { setCart([]); setPoInfo(null); setReceiptInfo(null); setOkMsg(''); setError(''); }}
              disabled={cart.length === 0} data-testid="barcode-clear-btn">Kosongkan</Button>
            <Button onClick={printPdf}
              disabled={busy || overLimit || bisaDicetak.length === 0}
              data-testid="barcode-print-btn">
              <Printer />{busy ? 'Menyiapkan…' : 'Cetak PDF'}
            </Button>
          </div>
        </GlassCard>
      </div>

      {/* Riwayat cetak */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="text-base font-semibold text-foreground">Riwayat cetak</p>
            <p className="text-xs text-muted-foreground">15 cetakan terakhir — menjawab "kenapa ada dua label berkode sama di gudang".</p>
          </div>
          <TombolUnduh namaBerkas="riwayat-cetak-barcode" namaLembar="Riwayat cetak" baris={history} testId="barcode-history-unduh"
            kolom={[
              { label: 'No. cetak', nilai: (h) => h.job_number }, { label: 'Jenis', nilai: jenisRiwayat },
              { label: 'Sumber', nilai: sumberRiwayat },
              { label: 'Item', nilai: (h) => Number(h.item_count || 0) }, { label: 'Lembar', nilai: (h) => Number(h.total_labels || 0) },
              { label: 'Oleh', nilai: (h) => h.created_by_name || '' },
              { label: 'Waktu', nilai: (h) => formatDateTimeID(h.created_at, { fallback: '' }) },
            ]} />
        </div>
        <TabelData kolom={kolomRiwayat} baris={history} testId="barcode-history-table"
          kosong={<div data-testid="barcode-history-empty"><EmptyState title="Belum ada riwayat cetak" /></div>} />
      </div>
    </PageLayout>
  );
}

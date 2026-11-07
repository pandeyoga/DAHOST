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
import { formatDateTimeID } from '@/lib/format';
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

const MAX_LABELS = 500;

const KINDS = [
  { key: 'material', label: 'Bahan & aksesoris' },
  { key: 'fg', label: 'Barang jadi' },
];
const JENIS_USAHA = { internal: 'Produksi internal', maklon: 'Maklon', customer_po: 'Customer PO' };
const jenisUsaha = (v) => JENIS_USAHA[v] || (v ? 'Lainnya' : '—');
const angka = (n) => Number(n || 0).toLocaleString('id-ID');

export default function WMSBarcodeModule() {
  const [kind, setKind] = useState('material');
  const [q, setQ] = useState('');
  const [cari, setCari] = useState('');
  const [items, setItems] = useState([]);
  const [itemsMeta, setItemsMeta] = useState({ total: 0, returned: 0 });
  const [loadingItems, setLoadingItems] = useState(false);
  const [cart, setCart] = useState([]);
  const [includeStock, setIncludeStock] = useState(true);

  // 2026-11-02 (keputusan owner): ukuran label barang jadi — standar 100×70 / hangtag 70×40

  const [fgSize, setFgSize] = useState('standard');
  const [note, setNote] = useState('');
  const [pos, setPos] = useState([]);
  const [poId, setPoId] = useState('');
  const [poInfo, setPoInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [okMsg, setOkMsg] = useState('');
  const [history, setHistory] = useState([]);

  // Ketikan pencarian diteruskan setelah jeda singkat (Enter langsung mencari).
  useEffect(() => {
    const t = setTimeout(() => setQ(cari.trim()), 300);
    return () => clearTimeout(t);
  }, [cari]);

  const loadItems = useCallback(async () => {
    setLoadingItems(true);
    try {
      const d = await apiGet(`/wms/barcode/items?kind=${kind}&q=${encodeURIComponent(q)}&limit=60`);
      setItems(d.items || []);
      setItemsMeta({ total: d.total || 0, returned: d.returned || 0 });
    } catch (e) { setError(e.message); } finally { setLoadingItems(false); }
  }, [kind, q]);

  const loadHistory = useCallback(async () => {
    try { setHistory(await apiGet('/wms/barcode/history?limit=15')); } catch { /* riwayat opsional */ }
  }, []);

  useEffect(() => { loadItems(); }, [loadItems]);
  useEffect(() => { loadHistory(); }, [loadHistory]);
  useEffect(() => {
    // 100 PO produksi terbaru (batas maksimum API; dulu 40 → PO lebih lama tidak bisa dipilih)
    apiGet('/wms/barcode/production-options?limit=100').then(setPos).catch(() => setPos([]));
  }, []);

  const totalLabels = useMemo(
    () => cart.reduce((s, r) => s + (Number(r.copies) || 0), 0), [cart]);
  const unlinked = useMemo(() => cart.filter(r => r.master_linked === false), [cart]);
  const overLimit = totalLabels > MAX_LABELS;

  const addItem = (it) => {
    setOkMsg('');
    setCart(prev => {
      const found = prev.find(r => r.code === it.code);
      if (found) return prev.map(r => r.code === it.code ? { ...r, copies: (Number(r.copies) || 0) + 1 } : r);
      return [...prev, {
        material_id: it.id, code: it.code, name: it.name, size: it.size,
        color: it.color, copies: 1, master_linked: true,
      }];
    });
  };

  const setCopies = (code, val) => setCart(prev => prev.map(
    r => r.code === code ? { ...r, copies: val === '' ? '' : Math.max(1, Math.min(200, Number(val) || 1)) } : r));
  const removeRow = (code) => setCart(prev => prev.filter(r => r.code !== code));

  const loadFromPO = async () => {
    if (!poId) return;
    setError(''); setOkMsg(''); setBusy(true);
    try {
      const d = await apiGet(`/wms/barcode/from-production?po_id=${encodeURIComponent(poId)}`);
      setKind('fg');
      setPoInfo(d);
      setCart((d.rows || []).map(r => ({ ...r, copies: Math.max(1, Math.min(200, r.copies || 1)) })));
      setOkMsg(`${(d.rows || []).length} artikel dari ${d.po_number} dimuat · ${d.total_copies} label mengikuti jumlah produksi`);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const printPdf = async () => {
    setError(''); setOkMsg(''); setBusy(true);
    try {
      const res = await apiFetch('/wms/barcode/batch-pdf', {
        method: 'POST',
        body: JSON.stringify({
          kind,
          rows: cart.filter(r => r.master_linked !== false)
            .map(r => ({ id: r.material_id || undefined, code: r.code, copies: Number(r.copies) || 1 })),
          include_stock: kind === 'material' ? includeStock : false,

          size: kind === 'fg' ? fgSize : 'standard',
          source: poInfo ? 'produksi' : 'manual',
          po_id: poInfo?.po_id || null,
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
    { kunci: 'name', label: 'Nama', hp: 'keterangan', isi: (it) => it.name },
    { kunci: 'unit', label: 'Satuan', isi: (it) => <span className="text-muted-foreground">{it.unit}</span> },
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
        {r.master_linked === false && (
          <p className="mt-0.5 text-xs text-[hsl(var(--danger-text))]" data-testid={`barcode-unlinked-${r.code}`}>
            Belum ada di master barang jadi — labelnya tidak bisa dicetak.{r.reason ? ` ${r.reason}` : ''}
          </p>
        )}
      </div>) },
    { kunci: 'name', label: 'Nama', hp: 'keterangan', isi: (r) => r.name },
    { kunci: 'varian', label: 'Varian', isi: (r) => [r.color, r.size].filter(Boolean).join(' · ') || '—' },
    { kunci: 'copies', label: 'Lembar', rata: 'kanan', isi: (r) => (
      <Input type="number" min="1" max="200" value={r.copies} onChange={e => setCopies(r.code, e.target.value)}
        className="ml-auto h-8 w-20 text-right" aria-label={`Jumlah lembar ${r.code}`} data-testid={`barcode-copies-${r.code}`} />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button variant="ghost" size="icon-sm" onClick={() => removeRow(r.code)} title="Hapus baris" aria-label={`Hapus ${r.code} dari daftar cetak`}
        data-testid={`barcode-remove-${r.code}`}><Trash2 /></Button>) },
  ];
  const kolomRiwayat = [
    { kunci: 'job', label: 'No. cetak', hp: 'judul', isi: (h) => <span className="tabular-nums" data-testid={`barcode-history-${h.job_number}`}>{h.job_number}</span> },
    { kunci: 'kind', label: 'Jenis', isi: (h) => (h.kind === 'fg' ? (h.size === 'hangtag' ? 'Barang jadi · hangtag' : 'Barang jadi') : 'Bahan') },
    { kunci: 'source', label: 'Sumber', isi: (h) => (h.source === 'produksi' ? 'Dari produksi' : 'Manual') },
    { kunci: 'items', label: 'Item', rata: 'kanan', isi: (h) => <span className="tabular-nums">{angka(h.item_count)}</span> },
    { kunci: 'labels', label: 'Lembar', rata: 'kanan', isi: (h) => <span className="tabular-nums font-medium">{angka(h.total_labels)}</span> },
    { kunci: 'by', label: 'Oleh', isi: (h) => h.created_by_name || '—' },
    { kunci: 'at', label: 'Waktu', hp: 'keterangan', isi: (h) => formatDateTimeID(h.created_at) },
  ];
  const jenisRiwayat = (h) => (h.kind === 'fg' ? (h.size === 'hangtag' ? 'Barang jadi · hangtag' : 'Barang jadi') : 'Bahan');

  return (
    <PageLayout testId="wms-barcode-page" title="Buat barcode"
      subtitle="Cetak label barcode bahan, aksesoris, dan barang jadi; kodenya selalu diambil dari master."
      filters={<>
        <FilterChips options={KINDS} value={kind} onChange={(id) => { setKind(id); setPoInfo(null); }} hideWhenEmpty={false}
          className="w-full sm:w-auto" testId="barcode-tab" ariaLabel="Jenis barang" />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={e => setCari(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { if (cari.trim() === q) loadItems(); else setQ(cari.trim()); } }}
            placeholder="Cari kode atau nama item" className="pl-8" data-testid="barcode-search-input" />
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={loadItems} disabled={loadingItems}
            data-testid="barcode-search-btn">
            <RefreshCw className={loadingItems ? 'animate-spin' : ''} />
          </Button>
        </div>
      </>}
      summary={
        <GlassCard className="space-y-2 p-4">
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
          <p className="text-xs text-muted-foreground">Jumlah label mengikuti qty PO (100 PO terbaru) — tidak diketik ulang.</p>
          {poInfo && (
            <p className="text-sm text-muted-foreground" data-testid="barcode-po-info">
              Sumber: <span className="font-medium text-foreground">{poInfo.po_number}</span> ({jenisUsaha(poInfo.business_type)}) ·
              {' '}{poInfo.rows?.length || 0} artikel · {poInfo.total_copies} label
              {poInfo.unlinked_count > 0 && (
                <span className="text-[hsl(var(--danger-text))]"> · {poInfo.unlinked_count} artikel belum ada di master</span>
              )}
            </p>
          )}
        </GlassCard>
      }>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Pemilih dari master */}
        <GlassCard className="min-w-0 space-y-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-base font-semibold text-foreground">Pilih dari master</p>
              <p className="text-xs text-muted-foreground" data-testid="barcode-items-meta">
                Menampilkan {angka(itemsMeta.returned)} dari {angka(itemsMeta.total)} item{itemsMeta.total > itemsMeta.returned ? ' — persempit dengan pencarian' : ''}
              </p>
            </div>
            <TombolUnduh namaBerkas={`master-barcode-${kind}`} namaLembar="Master" baris={items} testId="barcode-items-unduh"
              kolom={[
                { label: 'Kode', nilai: (it) => it.code }, { label: 'Nama', nilai: (it) => it.name },
                { label: 'Satuan', nilai: (it) => it.unit || '' }, { label: 'Warna', nilai: (it) => it.color || '' },
                { label: 'Ukuran', nilai: (it) => it.size || '' },
              ]} />
          </div>
          <div className="max-h-[28rem] overflow-y-auto">
            <TabelData kolom={kolomMaster} baris={items} testId="barcode-items-table"
              kosong={<p className="py-6 text-center text-sm text-muted-foreground" data-testid="barcode-items-empty">Tidak ada item yang cocok.</p>} />
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
                { label: 'Varian', nilai: (r) => [r.color, r.size].filter(Boolean).join(' · ') },
                { label: 'Lembar', nilai: (r) => Number(r.copies || 0) },
                { label: 'Ada di master', nilai: (r) => (r.master_linked === false ? 'Tidak' : 'Ya') },
              ]} />
          </div>

          <TabelData kolom={kolomCetak} baris={cart} kunci={(r) => r.code} testId="barcode-cart-table"
            kosong={
              <div data-testid="barcode-cart-empty">
                <EmptyState className="py-6" title="Belum ada item dipilih" description="Pilih dari master, atau ambil otomatis dari PO produksi." />
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
              Cetak stok & lokasi di label
            </label>
          )}

          <Isian label="Catatan cetak" petunjuk="Opsional" htmlFor="barcode-note">
            <Input id="barcode-note" value={note} onChange={e => setNote(e.target.value)}
              placeholder="mis. label rak B, giliran pagi" data-testid="barcode-note-input" />
          </Isian>

          {unlinked.length > 0 && (
            <Notice tone="danger" icon={AlertTriangle} testId="barcode-unlinked-warning">
              {unlinked.length} artikel PO belum punya varian di master barang jadi, jadi labelnya tidak dicetak. Buat variannya
              dulu di Master Produk — mencetak barcode dengan kode yang tidak dikenal sistem hanya memindahkan masalahnya ke rak.
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
            <Button variant="outline" onClick={() => { setCart([]); setPoInfo(null); setOkMsg(''); setError(''); }}
              disabled={cart.length === 0} data-testid="barcode-clear-btn">Kosongkan</Button>
            <Button onClick={printPdf}
              disabled={busy || overLimit || cart.filter(r => r.master_linked !== false).length === 0}
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
              { label: 'Sumber', nilai: (h) => (h.source === 'produksi' ? 'Dari produksi' : 'Manual') },
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

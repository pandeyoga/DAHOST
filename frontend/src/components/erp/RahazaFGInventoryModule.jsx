/**
 * Produk jadi (Portal Gudang › Master Item › tab "Produk jadi") — stok barang jadi + pengeluaran manual.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul tersembunyi di dalam hub), kartu angka = StatTile berketerangan,
 * tampilan Stok / Matriks / Pengeluaran / Riwayat = tab Radix (di dalam hub otomatis berupa pil), tabel → kartu
 * ringkas di HP, unduh Excel/CSV per tampilan, form "Keluarkan stok" = FormPopup panjang (dulu panel merah yang
 * terbuka di atas halaman). Field, validasi, dan API tidak berubah.
 *
 * Angka (diverifikasi 8 Nov 2026 di DB uji):
 *  • Produk jadi = jumlah baris /api/rahaza/materials?type=fg (615 aktif = pagination.total tab hub), ikut pencarian.
 *  • Stok di gudang = Σ qty /api/rahaza/material-stock untuk produk jadi itu (DB uji: −1 pcs, satu baris minus).
 *  • Masuk/keluar hari ini = dari 100 pergerakan terakhir /api/rahaza/fg-movements (sumber sama dengan tab Riwayat)
 *    — keterangannya kini menyebut batas itu; dulu "+0"/"−0" tanpa keterangan.
 *  • Hitungan di label tab Pengeluaran/Riwayat dihapus: itu panjang halaman API (maks 50/100), bukan total.
 *
 * 2026-11-10 (owner: "barang keluar tanpa scan bisa dicari dan bisa pilih multiple"): "Keluarkan stok" kini BANYAK
 * produk sekaligus. Produk dicari & dicentang lewat PilihProdukJadi (stok per lokasi dari server), tiap produk memilih
 * lokasi asal & jumlahnya. Satu formulir = SATU nomor pengeluaran; server memproses tiap baris lewat jalur yang sama
 * dengan pengeluaran satu produk (POST /api/rahaza/fg-issue/batch — potong stok, riwayat, jurnal HPP WAC). Semua
 * baris diperiksa dulu: satu saja stoknya kurang ⇒ tidak ada yang dikeluarkan (aturan lama "stok harus cukup" tetap).
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { MinusCircle, RefreshCw, Search, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import { useToast } from '@/hooks/use-toast';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { formatDateID, formatDateTimeID } from '@/lib/format';
import FGStockMatrixView from './FGStockMatrixView';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';
import PilihProdukJadi, { kolomBarang } from './warehouse/PilihProdukJadi';
import { apiFetch } from '@/lib/api';

const REASON_OPTIONS = [
  { value: 'surat_jalan_internal', label: 'Surat jalan internal', tone: 'info' },
  { value: 'sample',               label: 'Sampel / contoh',      tone: 'info' },
  { value: 'koreksi_stok',         label: 'Koreksi stok',         tone: 'warning' },
  { value: 'retur',                label: 'Retur / rusak',        tone: 'danger' },
  { value: 'lainnya',              label: 'Lainnya',              tone: 'muted' },
];
const alasanDari = (v) => REASON_OPTIONS.find((r) => r.value === v) || { label: v || '—', tone: 'muted' };

const SOURCE_LABEL = {
  production_internal:      { label: 'Produksi internal', tone: 'info' },
  production_customer_po:   { label: 'Customer PO',       tone: 'warning' },
  production_packing_event: { label: 'Hasil packing',     tone: 'success' },
  shipment_dispatch:        { label: 'Surat jalan',       tone: 'danger' },
  manual_issue:             { label: 'Pengeluaran manual', tone: 'warning' },
};
const sumberDari = (v) => SOURCE_LABEL[v] || { label: v ? 'Lainnya' : '—', tone: 'muted' };

const EMPTY_FORM = { reason: 'surat_jalan_internal', customer_id: undefined, reference_number: '', notes: '' };
const idBaru = () => {
  try { if (window.crypto?.randomUUID) return window.crypto.randomUUID(); } catch (_) { /* noop */ }
  return `fgi-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
};
// Satu baris formulir: { item (dari /fg-pick), location_id, qty }. Lokasi bawaan = lokasi dengan stok terbanyak.
const barisBaru = (item) => ({ item, location_id: item.lokasi?.[0]?.location_id || '', qty: '' });
const stokDi = (b) => Number((b.item.lokasi || []).find((l) => l.location_id === b.location_id)?.qty || 0);
const galatBaris = (b) => {
  if (!b.location_id) return 'Pilih lokasi asal';
  if (b.qty === '' || b.qty === null || b.qty === undefined) return 'Isi jumlah';
  const n = Number(b.qty);
  if (!Number.isInteger(n) || n <= 0) return 'Jumlah harus angka bulat lebih dari 0';
  if (n > stokDi(b)) return `Melebihi stok tersedia (${stokDi(b)} pcs)`;
  return null;
};
const pcs = (n) => Number(n || 0).toLocaleString('id-ID');

export default function RahazaFGInventoryModule({ token }) {
  const { toast } = useToast();
  const [items,     setItems]     = useState([]);
  const [stocks,    setStocks]    = useState({});
  const [movements, setMovements] = useState([]);
  const [issues,    setIssues]    = useState([]);
  const [customers, setCustomers] = useState([]);
  const [loading,   setLoading]   = useState(true);
  const [search,    setSearch]    = useState('');
  const [cari,      setCari]      = useState('');
  const [activeTab, setActiveTab] = useState('stock');
  const [showIssueForm, setShowIssueForm] = useState(false);
  const [form,      setForm]      = useState(EMPTY_FORM);
  // SESI #27 — nomor dokumen pengeluaran FG mengikuti kebijakan owner.
  const numPolicy = useDocNumberPolicy('rahaza_fg_issues.issue_number',
                                       localStorage.getItem('erp_token'));
  const [issueNo, setIssueNo] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const h = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  useEffect(() => {
    const t = setTimeout(() => setSearch(cari.trim()), 300);
    return () => clearTimeout(t);
  }, [cari]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ type: 'fg' });
      if (search) params.set('search', search);
      const [matR, stockR, movR, issR, custR] = await Promise.all([
        fetch(`/api/rahaza/materials?${params}`, { headers: h }),
        fetch('/api/rahaza/material-stock', { headers: h }),
        fetch('/api/rahaza/fg-movements?limit=100', { headers: h }),
        fetch('/api/rahaza/fg-issues?limit=50', { headers: h }),
        fetch('/api/rahaza/customers?limit=200', { headers: h }),
      ]);
      if (matR.ok)  setItems(await matR.json());
      if (movR.ok)  setMovements(await movR.json());
      if (issR.ok)  setIssues(await issR.json());
      if (custR.ok) setCustomers(await custR.json());
      if (stockR.ok) {
        const sd = await stockR.json();
        const map = {};
        const rows = Array.isArray(sd) ? sd : (sd.rows || []);
        rows.forEach(s => {
          map[s.material_id] = (map[s.material_id] || 0) + (s.qty || 0);
        });
        setStocks(map);
      }
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, search]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // KPIs
  const totalQty     = items.reduce((a, m) => a + (stocks[m.id] || 0), 0);
  const today        = new Date().toDateString();
  const inToday  = movements.filter(m => m.direction === 'in'  && new Date(m.timestamp).toDateString() === today).reduce((a,m)=>a+m.qty,0);
  const outToday = movements.filter(m => m.direction === 'out' && new Date(m.timestamp).toDateString() === today).reduce((a,m)=>a+m.qty,0);

  // ── Formulir "Keluarkan stok" banyak produk (10 Nov 2026) ─────────────────
  // 2026-11-02 — No.18(a) tetap: lokasi asal WAJIB per produk, pilihannya hanya lokasi yang memegang stok produk
  // itu (data `lokasi` dari server, /fg-pick). Bawaan = lokasi dengan stok terbanyak, bisa diganti.
  const [baris, setBaris] = useState([]);
  const [galatSimpan, setGalatSimpan] = useState('');
  // Id kiriman dibuat saat formulir dibuka: Simpan yang terkirim dua kali tidak mengeluarkan stok dua kali.
  const batchId = useRef('');
  const terpilihMap = useMemo(() => Object.fromEntries(baris.map((b) => [b.item.id, true])), [baris]);
  const ubahPilihan = (item, centang) => setBaris((bs) => (centang
    ? (bs.some((b) => b.item.id === item.id) ? bs : [...bs, barisBaru(item)])
    : bs.filter((b) => b.item.id !== item.id)));
  const ubahBaris = (id, patch) => setBaris((bs) => bs.map((b) => (b.item.id === id ? { ...b, ...patch } : b)));
  const totalPcs = baris.reduce((a, b) => a + (galatBaris(b) ? 0 : Number(b.qty)), 0);
  const barisSalah = baris.find((b) => galatBaris(b));

  const tutupForm = () => { setShowIssueForm(false); setForm(EMPTY_FORM); setBaris([]); setGalatSimpan(''); };

  const handleSubmitIssue = async () => {
    if (!baris.length) return toast({ title: 'Pilih produk jadi terlebih dahulu', variant: 'destructive' });
    if (barisSalah) return toast({ title: `${barisSalah.item.code}: ${galatBaris(barisSalah)}`, variant: 'destructive' });
    setSubmitting(true);
    setGalatSimpan('');
    try {
      const res = await apiFetch('/api/rahaza/fg-issue/batch', {
        method: 'POST',
        body: JSON.stringify({
          ...form, client_batch_id: batchId.current,
          items: baris.map((b) => ({ material_id: b.item.id, location_id: b.location_id, qty: Number(b.qty), code: b.item.code })),
          ...docNumberPayload(numPolicy, 'issue_number', issueNo),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setGalatSimpan(data.detail || 'Gagal membuat pengeluaran'); return; }
      const lines = data.lines || [];
      const pcsKeluar = lines.reduce((a, l) => a + Number(l.qty || 0), 0);
      toast({ title: `Pengeluaran ${data.issue_number} tercatat — ${lines.length} produk, ${pcs(pcsKeluar)} pcs dikurangi dari stok` });
      if ((data.failed || []).length) {
        toast({ variant: 'destructive', title: `${data.failed.length} produk tidak dikeluarkan`,
          description: data.failed.map((f) => `${f.code}: ${f.error}`).join(' · ') });
      }
      const jurnalGagal = lines.filter((l) => l.gl_post_error);
      if (jurnalGagal.length) {
        toast({ variant: 'destructive', title: 'Stok sudah keluar, tetapi jurnal HPP belum tercatat',
          description: jurnalGagal.map((l) => `${l.fg_code}: ${l.gl_post_error}`).join(' · ') });
      }
      tutupForm();
      fetchData();
    } catch (e) {
      setGalatSimpan('Jaringan putus — belum pasti tercatat. Tekan simpan lagi tanpa mengubah isian: pengeluaran yang sudah tercatat tidak dibuat dua kali.');
    } finally { setSubmitting(false); }
  };

  // Tombol "Keluarkan" di baris tabel / matriks: produk itu langsung masuk daftar (data lokasi dari server).
  const bukaForm = async (materialId, kodeCadangan) => {
    setForm(EMPTY_FORM);
    setBaris([]);
    setGalatSimpan('');
    setIssueNo('');
    batchId.current = idBaru();
    setShowIssueForm(true);
    const kode = items.find((m) => m.id === materialId)?.code || kodeCadangan;
    if (!materialId || !kode) return;
    try {
      const r = await apiFetch(`/api/rahaza/fg-pick?ada_stok=true&q=${encodeURIComponent(kode)}`);
      const d = r.ok ? await r.json() : {};
      const it = (d.items || []).find((x) => x.id === materialId);
      if (it) setBaris((bs) => (bs.some((b) => b.item.id === it.id) ? bs : [...bs, barisBaru(it)]));
    } catch (_) { /* produk tetap bisa dicari manual di formulir */ }
  };

  // RC-UI-03: client-side pagination (25/halaman) untuk 3 tabel (hook di tingkat atas)
  const itemsPg     = useClientPagination(items, 25);
  const issuesPg    = useClientPagination(issues, 25);
  const movementsPg = useClientPagination(movements, 25);
  const pgAktif = activeTab === 'stock' ? itemsPg : activeTab === 'issues' ? issuesPg : activeTab === 'movements' ? movementsPg : null;

  const statusStok = (qty) => (qty > 0 ? <StatusBadge status="ada" label="Ada stok" tone="success" />
    : qty < 0 ? <StatusBadge status="minus" label="Minus" tone="danger" />
      : <StatusBadge status="kosong" label="Kosong" tone="muted" />);

  const kolomStok = [
    { kunci: 'code', label: 'Kode', hp: 'judul', isi: (m) => <span className="tabular-nums">{m.code}</span> },
    { kunci: 'name', label: 'Nama produk', hp: 'keterangan', isi: (m) => <span className="text-foreground">{m.name}</span> },
    { kunci: 'qty', label: 'Stok (pcs)', rata: 'kanan', isi: (m) => <span className="tabular-nums font-medium">{pcs(stocks[m.id] || 0)}</span> },
    { kunci: 'status', label: 'Status', hp: false, isi: (m) => statusStok(stocks[m.id] || 0) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (m) => ((stocks[m.id] || 0) > 0 ? (
      <Button size="sm" variant="outline" onClick={() => bukaForm(m.id)} data-testid={`fg-issue-quick-${m.code}`}>
        <MinusCircle />Keluarkan
      </Button>
    ) : null) },
  ];
  const kolomPengeluaran = [
    { kunci: 'issue_number', label: 'No. pengeluaran', hp: 'judul', isi: (i) => <span className="tabular-nums">{i.issue_number}</span> },
    { kunci: 'fg', label: 'Produk', hp: false, isi: (i) => (
      <div className="min-w-0"><div className="tabular-nums text-xs text-muted-foreground">{i.fg_code}</div><div className="truncate">{i.fg_name}</div></div>) },
    { kunci: 'hp-ket', label: '', hp: 'keterangan', lebar: 'hidden', isi: (i) => [i.fg_code, i.fg_name].filter(Boolean).join(' · ') },
    { kunci: 'qty', label: 'Qty (pcs)', rata: 'kanan', isi: (i) => <span className="tabular-nums font-medium">{pcs(i.qty)}</span> },
    { kunci: 'reason', label: 'Alasan', hp: false, isi: (i) => { const a = alasanDari(i.reason); return <StatusBadge status={i.reason} label={a.label} tone={a.tone} />; } },
    { kunci: 'customer', label: 'Tujuan', hp: false, isi: (i) => i.customer_name || '—' },
    { kunci: 'ref', label: 'Referensi', hp: false, isi: (i) => i.reference_number || '—' },
    { kunci: 'by', label: 'Diproses oleh', hp: false, isi: (i) => i.issued_by || '—' },
    { kunci: 'tgl', label: 'Tanggal', isi: (i) => <span className="whitespace-nowrap">{formatDateID(i.issued_at)}</span> },
  ];
  const kolomRiwayat = [
    { kunci: 'waktu', label: 'Waktu', hp: false, isi: (mv) => <span className="whitespace-nowrap">{formatDateTimeID(mv.timestamp)}</span> },
    { kunci: 'fg_code', label: 'Kode', hp: 'judul', isi: (mv) => <span className="tabular-nums">{mv.fg_code}</span> },
    { kunci: 'hp-ket', label: '', hp: 'keterangan', lebar: 'hidden', isi: (mv) => `${formatDateTimeID(mv.timestamp)} · ${sumberDari(mv.source).label}` },
    { kunci: 'arah', label: 'Arah', hp: false, isi: (mv) => (mv.direction === 'in'
      ? <StatusBadge status="masuk" label="Masuk" tone="success" /> : <StatusBadge status="keluar" label="Keluar" tone="danger" />) },
    { kunci: 'qty', label: 'Qty (pcs)', rata: 'kanan', isi: (mv) => <span className="tabular-nums font-medium">{mv.direction === 'in' ? '' : '−'}{pcs(mv.qty)}</span> },
    { kunci: 'sumber', label: 'Sumber', hp: false, isi: (mv) => { const s = sumberDari(mv.source); return <StatusBadge status={mv.source} label={s.label} tone={s.tone} />; } },
    { kunci: 'ref', label: 'WO / SJ / referensi', hp: false, isi: (mv) => mv.wo_number || mv.shipment_number || mv.reference_number || '—' },
    { kunci: 'notes', label: 'Keterangan', hp: false, isi: (mv) => <span className="line-clamp-1 text-muted-foreground">{mv.notes || '—'}</span> },
  ];

  const unduh = activeTab === 'stock' ? (
    <TombolUnduh namaBerkas="stok-produk-jadi" namaLembar="Stok produk jadi" baris={items} testId="fg-unduh-stok"
      kolom={[
        { label: 'Kode', nilai: (m) => m.code },
        { label: 'Nama produk', nilai: (m) => m.name },
        { label: 'Stok (pcs)', nilai: (m) => Number(stocks[m.id] || 0) },
        { label: 'Status', nilai: (m) => ((stocks[m.id] || 0) > 0 ? 'Ada stok' : (stocks[m.id] || 0) < 0 ? 'Minus' : 'Kosong') },
      ]} />
  ) : activeTab === 'issues' ? (
    <TombolUnduh namaBerkas="pengeluaran-produk-jadi" namaLembar="Pengeluaran" baris={issues} testId="fg-unduh-pengeluaran"
      kolom={[
        { label: 'No. pengeluaran', nilai: (i) => i.issue_number },
        { label: 'Kode produk', nilai: (i) => i.fg_code },
        { label: 'Nama produk', nilai: (i) => i.fg_name },
        { label: 'Qty (pcs)', nilai: (i) => Number(i.qty || 0) },
        { label: 'Alasan', nilai: (i) => alasanDari(i.reason).label },
        { label: 'Tujuan', nilai: (i) => i.customer_name || '' },
        { label: 'Referensi', nilai: (i) => i.reference_number || '' },
        { label: 'Diproses oleh', nilai: (i) => i.issued_by || '' },
        { label: 'Tanggal', nilai: (i) => formatDateID(i.issued_at, { fallback: '' }) },
      ]} />
  ) : activeTab === 'movements' ? (
    <TombolUnduh namaBerkas="riwayat-produk-jadi" namaLembar="Riwayat" baris={movements} testId="fg-unduh-riwayat"
      kolom={[
        { label: 'Waktu', nilai: (mv) => formatDateTimeID(mv.timestamp, { fallback: '' }) },
        { label: 'Kode produk', nilai: (mv) => mv.fg_code },
        { label: 'Arah', nilai: (mv) => (mv.direction === 'in' ? 'Masuk' : 'Keluar') },
        { label: 'Qty (pcs)', nilai: (mv) => Number(mv.qty || 0) * (mv.direction === 'in' ? 1 : -1) },
        { label: 'Sumber', nilai: (mv) => sumberDari(mv.source).label },
        { label: 'WO / SJ / referensi', nilai: (mv) => mv.wo_number || mv.shipment_number || mv.reference_number || '' },
        { label: 'Keterangan', nilai: (mv) => mv.notes || '' },
      ]} />
  ) : null;

  return (
      <PageLayout testId="fg-inventory-page" title="Produk jadi"
        subtitle="Stok barang jadi dari produksi internal dan Customer PO, beserta pengeluarannya."
        actions={<Button onClick={() => bukaForm()} data-testid="fg-issue-btn"><MinusCircle />Keluarkan stok</Button>}
        filters={<>
          <FilterChips value={activeTab} onChange={setActiveTab} hideWhenEmpty={false} testId="fg-tab" ariaLabel="Tampilan" className="w-full sm:w-auto"
            options={[
              { key: 'stock', label: 'Stok' },
              { key: 'matrix', label: 'Matriks ukuran × warna' },
              { key: 'issues', label: 'Pengeluaran' },
              { key: 'movements', label: 'Riwayat' },
            ]} />
          {activeTab === 'stock' && (
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input placeholder="Cari produk jadi" className="pl-8" value={cari} onChange={e => setCari(e.target.value)}
                data-testid="fg-search" />
            </div>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-2">
          {unduh}
          <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData} disabled={loading}>
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
          </div>
        </>}
        summary={activeTab !== 'matrix' ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Produk jadi" value={pcs(items.length)} sub={search ? 'sesuai pencarian' : 'barang jadi aktif di master'} />
            <StatTile label="Stok di gudang" value={pcs(totalQty)} suffix="pcs" accent={totalQty < 0 ? 'danger' : 'default'}
              sub="jumlah stok semua lokasi" />
            <StatTile label="Masuk hari ini" value={pcs(inToday)} suffix="pcs" sub="dari 100 pergerakan terakhir" />
            <StatTile label="Keluar hari ini" value={pcs(outToday)} suffix="pcs" sub="dari 100 pergerakan terakhir" />
          </div>
        ) : null}
        footer={pgAktif && pgAktif.total > pgAktif.pageSize ? (
          <PaginationLite page={pgAktif.page} totalPages={pgAktif.totalPages} total={pgAktif.total} pageSize={pgAktif.pageSize} onPageChange={pgAktif.setPage} />
        ) : null}>

        {/* ── STOK ── */}
        {activeTab === 'stock' && (<>
          {loading && items.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Memuat produk jadi…</p>
          ) : (
            <TabelData kolom={kolomStok} baris={itemsPg.paged} testId="fg-stock-table"
              kosong={<EmptyState title={search ? 'Tidak ada produk jadi yang cocok' : 'Belum ada produk jadi'}
                description={search ? 'Ubah kata pencarian.' : 'Otomatis muncul saat WO selesai atau hasil packing dicatat.'} />} />
          )}
        </>)}

        {/* ── MATRIKS (P1-WH-3) ── */}
        {activeTab === 'matrix' && (<>
          <FGStockMatrixView
            token={token}
            onCellAction={(action, cell) => {
              if (action === 'issue') bukaForm(cell.material_id, cell.code);
            }}
          />
        </>)}

        {/* ── PENGELUARAN ── */}
        {activeTab === 'issues' && (<div className="space-y-2">
          {issues.length > 0 && <p className="text-xs text-muted-foreground">Menampilkan 50 pengeluaran terakhir.</p>}
          <TabelData kolom={kolomPengeluaran} baris={issuesPg.paged} testId="fg-issues-table"
            kosong={<EmptyState title="Belum ada pengeluaran stok produk jadi"
              action={<Button variant="outline" onClick={() => bukaForm()}><MinusCircle />Keluarkan stok</Button>} />} />
        </div>)}

        {/* ── RIWAYAT ── */}
        {activeTab === 'movements' && (<div className="space-y-2">
          {movements.length > 0 && <p className="text-xs text-muted-foreground">Menampilkan 100 pergerakan terakhir.</p>}
          <TabelData kolom={kolomRiwayat} baris={movementsPg.paged} testId="fg-movements-table"
            kosong={<EmptyState title="Belum ada pergerakan stok produk jadi" />} />
        </div>)}

        {/* ── FORM KELUARKAN STOK (popup) ── */}
        <FormPopup open={showIssueForm} onClose={tutupForm} ukuran="panjang"
          judul="Keluarkan stok produk jadi" testId="fg-issue-form"
          keterangan="Cari dan centang produk (boleh banyak), lalu pilih lokasi asal dan jumlahnya. Semua produk memakai satu nomor pengeluaran. Customer PO: stok berkurang otomatis saat surat jalan dikirim, bukan di sini."
          onSimpan={handleSubmitIssue} menyimpan={submitting}
          labelSimpan={baris.length ? `Keluarkan ${baris.length} produk · ${pcs(totalPcs)} pcs` : 'Keluarkan stok'}
          galat={galatSimpan /* galat per baris tampil di barisnya sendiri; kaki popup hanya galat server */}
          bisaSimpan={baris.length > 0 && !barisSalah}>
          <Isian label="Cari produk jadi" wajib>
            {showIssueForm && (
              <PilihProdukJadi adaStok terpilih={terpilihMap} onUbah={ubahPilihan} testId="fg-issue-cari" />
            )}
          </Isian>

          {/* Produk terpilih — lokasi asal wajib per produk (No.18a), jumlah ≤ stok lokasi itu */}
          <div className="space-y-2">
            <div className="text-sm font-medium">Dipilih ({baris.length} produk · {pcs(totalPcs)} pcs)</div>
            <TabelData baris={baris} kunci={(b) => b.item.id} testId="fg-issue-dipilih"
              kosong={<EmptyState title="Belum ada produk dipilih" description="Centang produk dari hasil cari di atas." />}
              kolom={[
                ...kolomBarang((b) => b.item),
                { kunci: 'lokasi', label: 'Lokasi asal', isi: (b) => (
                  <SmartNativeSelect value={b.location_id} className="w-full" wrapperClassName="w-full sm:w-52"
                    aria-label={`Lokasi asal ${b.item.code}`} data-testid={`fg-issue-location-${b.item.code}`}
                    onChange={(e) => ubahBaris(b.item.id, { location_id: e.target.value })}>
                    <option value="">Pilih lokasi</option>
                    {(b.item.lokasi || []).map((l) => (
                      <option key={l.location_id} value={l.location_id}>
                        {`${l.code ? `${l.code} · ` : ''}${l.name || ''} — ${pcs(l.qty)} pcs${l.jual ? '' : ' (bukan stok jual)'}`}
                      </option>
                    ))}
                  </SmartNativeSelect>
                ) },
                { kunci: 'qty', label: 'Jumlah (pcs)', rata: 'kanan', isi: (b) => {
                  const g = b.qty !== '' ? galatBaris(b) : null;
                  return (
                    <div className="flex flex-col items-end gap-0.5">
                      <Input type="number" min="1" max={stokDi(b)} value={b.qty} placeholder={`maks ${stokDi(b)}`}
                        aria-label={`Jumlah ${b.item.code}`} className="h-8 w-24 text-right text-sm"
                        onChange={(e) => ubahBaris(b.item.id, { qty: e.target.value })} data-testid={`fg-issue-qty-${b.item.code}`} />
                      {g && <span className="block max-w-[9rem] whitespace-normal text-right text-xs text-[hsl(var(--danger-text))]">{g}</span>}
                    </div>
                  );
                } },
                { kunci: 'hapus', label: '', hp: 'aksi', lebar: 'w-10', isi: (b) => (
                  <Button type="button" size="icon-sm" variant="ghost" onClick={() => ubahPilihan(b.item, false)}
                    aria-label={`Hapus ${b.item.code} dari pilihan`} title="Hapus dari pilihan">
                    <X />
                  </Button>
                ) },
              ]} />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Alasan pengeluaran" wajib>
              <SmartNativeSelect value={form.reason} searchable={false} className="w-full" data-testid="fg-issue-reason"
                onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}>
                {REASON_OPTIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </SmartNativeSelect>
            </Isian>
            <Isian label="Tujuan / customer" petunjuk="Opsional">
              <SmartNativeSelect value={form.customer_id || ''} className="w-full" data-testid="fg-issue-customer"
                onChange={e => setForm(f => ({ ...f, customer_id: e.target.value || undefined }))}>
                <option value="">Tidak ada</option>
                {customers.map(c => <option key={c.id} value={c.id}>{`${c.code} — ${c.name}`}</option>)}
              </SmartNativeSelect>
            </Isian>
            <Isian label="No. referensi / SJ manual" petunjuk="Opsional" htmlFor="fg-issue-ref">
              <Input id="fg-issue-ref" value={form.reference_number}
                onChange={e => setForm(f => ({ ...f, reference_number: e.target.value }))}
                placeholder="Contoh: SJ-2026-001" data-testid="fg-issue-reference" />
            </Isian>
          </div>
          <Isian label="Catatan" htmlFor="fg-issue-notes-in">
            <Input id="fg-issue-notes-in" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              placeholder="Catatan tambahan" data-testid="fg-issue-notes" />
          </Isian>
          {/* SESI #27 — nomor dokumen (otomatis/manual sesuai setelan owner); SATU nomor untuk semua produk */}
          <DocNumberField policy={numPolicy} value={issueNo} onChange={setIssueNo}
            testId="fg-issue-docnum" label="Nomor pengeluaran barang jadi" />
        </FormPopup>
      </PageLayout>
  );
}

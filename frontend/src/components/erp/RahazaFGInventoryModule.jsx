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
 */
import { useState, useEffect, useCallback } from 'react';
import { MinusCircle, RefreshCw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
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

const EMPTY_FORM = { material_id: '', location_id: '', qty: '', reason: 'surat_jalan_internal', customer_id: undefined, reference_number: '', notes: '' };
const pcs = (n) => Number(n || 0).toLocaleString('id-ID');

export default function RahazaFGInventoryModule({ token }) {
  const { toast } = useToast();
  const [items,     setItems]     = useState([]);
  const [stocks,    setStocks]    = useState({});
  const [stockRows, setStockRows] = useState([]);
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
        setStockRows(rows);
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

  // Get current stock for selected FG in form
  const selectedMat   = items.find(m => m.id === form.material_id);
  // 2026-11-02 — No.18(a): lokasi asal WAJIB dipilih (dulu backend diam-diam membaca
  // "lokasi aktif pertama" → stok 36 pcs di rak terbaca 0). Pilihan = lokasi yang
  // benar-benar memegang stok FG ini; tidak ada pilihan bawaan.
  const locOptions = selectedMat
    ? stockRows.filter(r => r.material_id === selectedMat.id && Number(r.qty || 0) > 0)
    : [];
  const selectedLoc = locOptions.find(r => r.location_id === form.location_id);
  const availableStock = selectedLoc ? Number(selectedLoc.qty || 0) : 0;

  const handleSubmitIssue = async () => {
    if (!form.material_id)  return toast({ title: 'Pilih produk jadi terlebih dahulu', variant: 'destructive' });
    if (!form.location_id)  return toast({ title: 'Pilih lokasi asal barang terlebih dahulu', variant: 'destructive' });
    if (!form.qty || parseFloat(form.qty) <= 0) return toast({ title: 'Qty harus lebih dari 0', variant: 'destructive' });
    if (parseFloat(form.qty) > availableStock)  return toast({ title: `Stok tidak cukup. Tersedia: ${availableStock} pcs`, variant: 'destructive' });
    setSubmitting(true);
    try {
      const res = await fetch('/api/rahaza/fg-issue', {
        method: 'POST',
        headers: h,
        body: JSON.stringify({ ...form, qty: parseInt(form.qty),
                               ...docNumberPayload(numPolicy, 'issue_number', issueNo) }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Gagal membuat pengeluaran');
      toast({ title: `Pengeluaran ${data.issue_number} tercatat — ${form.qty} pcs dikurangi dari stok` });
      setForm(EMPTY_FORM);
      setShowIssueForm(false);
      fetchData();
    } catch (e) {
      toast({ title: e.message, variant: 'destructive' });
    } finally { setSubmitting(false); }
  };

  const bukaForm = (materialId) => {
    if (materialId) setForm(f => ({ ...f, material_id: materialId, location_id: '', qty: '' }));
    setShowIssueForm(true);
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
    { kunci: 'status', label: 'Status', isi: (m) => statusStok(stocks[m.id] || 0) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (m) => ((stocks[m.id] || 0) > 0 ? (
      <Button size="sm" variant="outline" onClick={() => bukaForm(m.id)} data-testid={`fg-issue-quick-${m.code}`}>
        <MinusCircle />Keluarkan
      </Button>
    ) : null) },
  ];
  const kolomPengeluaran = [
    { kunci: 'issue_number', label: 'No. pengeluaran', hp: 'judul', isi: (i) => <span className="tabular-nums">{i.issue_number}</span> },
    { kunci: 'fg', label: 'Produk', hp: 'keterangan', isi: (i) => (
      <div className="min-w-0"><div className="tabular-nums text-xs text-muted-foreground">{i.fg_code}</div><div className="truncate">{i.fg_name}</div></div>) },
    { kunci: 'qty', label: 'Qty (pcs)', rata: 'kanan', isi: (i) => <span className="tabular-nums font-medium">{pcs(i.qty)}</span> },
    { kunci: 'reason', label: 'Alasan', isi: (i) => { const a = alasanDari(i.reason); return <StatusBadge status={i.reason} label={a.label} tone={a.tone} />; } },
    { kunci: 'customer', label: 'Tujuan', isi: (i) => i.customer_name || '—' },
    { kunci: 'ref', label: 'Referensi', isi: (i) => i.reference_number || '—' },
    { kunci: 'by', label: 'Diproses oleh', isi: (i) => i.issued_by || '—' },
    { kunci: 'tgl', label: 'Tanggal', isi: (i) => <span className="whitespace-nowrap">{formatDateID(i.issued_at)}</span> },
  ];
  const kolomRiwayat = [
    { kunci: 'waktu', label: 'Waktu', hp: 'keterangan', isi: (mv) => <span className="whitespace-nowrap">{formatDateTimeID(mv.timestamp)}</span> },
    { kunci: 'fg_code', label: 'Kode', hp: 'judul', isi: (mv) => <span className="tabular-nums">{mv.fg_code}</span> },
    { kunci: 'arah', label: 'Arah', isi: (mv) => (mv.direction === 'in'
      ? <StatusBadge status="masuk" label="Masuk" tone="success" /> : <StatusBadge status="keluar" label="Keluar" tone="danger" />) },
    { kunci: 'qty', label: 'Qty (pcs)', rata: 'kanan', isi: (mv) => <span className="tabular-nums font-medium">{mv.direction === 'in' ? '' : '−'}{pcs(mv.qty)}</span> },
    { kunci: 'sumber', label: 'Sumber', isi: (mv) => { const s = sumberDari(mv.source); return <StatusBadge status={mv.source} label={s.label} tone={s.tone} />; } },
    { kunci: 'ref', label: 'WO / SJ / referensi', isi: (mv) => mv.wo_number || mv.shipment_number || mv.reference_number || '—' },
    { kunci: 'notes', label: 'Keterangan', isi: (mv) => <span className="line-clamp-1 text-muted-foreground">{mv.notes || '—'}</span> },
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
    <Tabs value={activeTab} onValueChange={setActiveTab}>
      <PageLayout testId="fg-inventory-page" title="Produk jadi"
        subtitle="Stok barang jadi dari produksi internal dan Customer PO, beserta pengeluarannya."
        actions={<Button onClick={() => bukaForm()} data-testid="fg-issue-btn"><MinusCircle />Keluarkan stok</Button>}
        filters={<>
          <TabsList>
            <TabsTrigger value="stock" data-testid="fg-tab-stock">Stok</TabsTrigger>
            <TabsTrigger value="matrix" data-testid="fg-tab-matrix">Matriks ukuran × warna</TabsTrigger>
            <TabsTrigger value="issues" data-testid="fg-tab-issues">Pengeluaran</TabsTrigger>
            <TabsTrigger value="movements" data-testid="fg-tab-movements">Riwayat</TabsTrigger>
          </TabsList>
          {activeTab === 'stock' && (
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input placeholder="Cari produk jadi" className="pl-8" value={cari} onChange={e => setCari(e.target.value)}
                data-testid="fg-search" />
            </div>
          )}
        </>}
        tools={<>
          {unduh}
          <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData} disabled={loading}>
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
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
        <TabsContent value="stock" className="mt-0">
          {loading && items.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">Memuat produk jadi…</p>
          ) : (
            <TabelData kolom={kolomStok} baris={itemsPg.paged} testId="fg-stock-table"
              kosong={<EmptyState title={search ? 'Tidak ada produk jadi yang cocok' : 'Belum ada produk jadi'}
                description={search ? 'Ubah kata pencarian.' : 'Otomatis muncul saat WO selesai atau hasil packing dicatat.'} />} />
          )}
        </TabsContent>

        {/* ── MATRIKS (P1-WH-3) ── */}
        <TabsContent value="matrix" className="mt-0">
          <FGStockMatrixView
            token={token}
            onCellAction={(action, cell) => {
              if (action === 'issue') {
                setForm(f => ({ ...f, material_id: cell.material_id, location_id: '', qty: '' }));
                setShowIssueForm(true);
              }
            }}
          />
        </TabsContent>

        {/* ── PENGELUARAN ── */}
        <TabsContent value="issues" className="mt-0 space-y-2">
          {issues.length > 0 && <p className="text-xs text-muted-foreground">Menampilkan 50 pengeluaran terakhir.</p>}
          <TabelData kolom={kolomPengeluaran} baris={issuesPg.paged} testId="fg-issues-table"
            kosong={<EmptyState title="Belum ada pengeluaran stok produk jadi"
              action={<Button variant="outline" onClick={() => bukaForm()}><MinusCircle />Keluarkan stok</Button>} />} />
        </TabsContent>

        {/* ── RIWAYAT ── */}
        <TabsContent value="movements" className="mt-0 space-y-2">
          {movements.length > 0 && <p className="text-xs text-muted-foreground">Menampilkan 100 pergerakan terakhir.</p>}
          <TabelData kolom={kolomRiwayat} baris={movementsPg.paged} testId="fg-movements-table"
            kosong={<EmptyState title="Belum ada pergerakan stok produk jadi" />} />
        </TabsContent>

        {/* ── FORM KELUARKAN STOK (popup) ── */}
        <FormPopup open={showIssueForm} onClose={() => { setShowIssueForm(false); setForm(EMPTY_FORM); }} ukuran="panjang"
          judul="Keluarkan stok produk jadi" testId="fg-issue-form"
          keterangan="Produksi internal: WO selesai menambah stok, pengeluaran dicatat manual di sini. Customer PO: stok berkurang otomatis saat surat jalan dikirim."
          onSimpan={handleSubmitIssue} menyimpan={submitting} labelSimpan="Keluarkan stok"
          bisaSimpan={!!form.material_id && !!form.qty && parseFloat(form.qty) <= availableStock}>
          <Isian label="Produk jadi" wajib>
            <SmartNativeSelect value={form.material_id} className="w-full" data-testid="fg-issue-material"
              onChange={e => setForm(f => ({ ...f, material_id: e.target.value, location_id: '', qty: '' }))}>
              <option value="">Pilih produk jadi</option>
              {items.map(m => (
                <option key={m.id} value={m.id} disabled={(stocks[m.id] || 0) <= 0}>
                  {`${m.code} — ${m.name} (${stocks[m.id] || 0} pcs tersedia)`}
                </option>
              ))}
            </SmartNativeSelect>
          </Isian>

          {/* Lokasi asal — wajib dipilih (No.18a) */}
          <Isian label="Lokasi asal" wajib
            galat={form.material_id && locOptions.length === 0 ? 'Produk ini tidak punya stok di lokasi mana pun.' : undefined}
            petunjuk={form.location_id ? `Stok di lokasi ini: ${availableStock} pcs` : undefined}>
            <SmartNativeSelect value={form.location_id} className="w-full" disabled={!form.material_id} required
              onChange={e => setForm(f => ({ ...f, location_id: e.target.value }))} data-testid="fg-issue-location">
              <option value="">{form.material_id ? 'Pilih lokasi' : 'Pilih produk jadi dulu'}</option>
              {locOptions.map(r => (
                <option key={r.location_id} value={r.location_id}>
                  {`${(r.location_code ? `${r.location_code} · ` : '') + (r.location_name || r.location_id)} — ${r.qty} pcs`}
                </option>
              ))}
            </SmartNativeSelect>
          </Isian>

          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Qty dikeluarkan (pcs)" wajib htmlFor="fg-issue-qty-in"
              galat={form.qty && parseFloat(form.qty) > availableStock ? 'Melebihi stok tersedia' : undefined}>
              <Input id="fg-issue-qty-in" type="number" min="1" max={availableStock} value={form.qty}
                onChange={e => setForm(f => ({ ...f, qty: e.target.value }))}
                placeholder={`maks ${availableStock}`} data-testid="fg-issue-qty" />
            </Isian>
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
          {/* SESI #27 — nomor dokumen (otomatis/manual sesuai setelan owner) */}
          <DocNumberField policy={numPolicy} value={issueNo} onChange={setIssueNo}
            testId="fg-issue-docnum" label="Nomor pengeluaran barang jadi" />
        </FormPopup>
      </PageLayout>
    </Tabs>
  );
}

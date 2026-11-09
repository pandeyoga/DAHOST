/**
 * Roll Kain — stok kain per gulungan (barcode, status QC, posisi).
 * P0-WH-1: Fabric roll tracking dengan barcode, QC status, position management.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (dulu kepala bergradien "Fabric Roll Tracking" dengan ikon,
 * tab bar abu, tampilan kartu besar); tab status → pil penyaring; daftar = TabelData dengan pilihan urutan dan
 * unduhan Excel + CSV; aksi baris maks 2 (sisanya "Lainnya"); semua form (simpan ke posisi, keluarkan,
 * terbitkan gulungan) = FormPopup; detail roll & hasil analisis AI = DetailPopup.
 * Perbaikan ikut: daftar dulu hanya memuat 50 roll pertama (bawaan server) lalu diurutkan/diunduh/dijumlah
 * seolah-olah semua — kini semua halaman dimuat (200 per permintaan).
 *
 * 10 Nov 2026 (keputusan owner): input roll MANUAL dihapus (tombol di kepala dan di tampilan kosong, beserta
 * popup isiannya; server `POST /api/wms/fabric-rolls` → 410). Roll manual berstatus Tersedia tanpa
 * menambah stok bahan dan tanpa jurnal ⇒ roll tanpa stok / dobel. Roll lahir dari Penerimaan Barang (rincian
 * gulungan), tab "Penerimaan tanpa roll", atau Impor roll stok awal. "Simpan ke posisi" kini memilih posisi dari
 * master struktur gudang (gudang → zona → rak → posisi) atau scan barcode — dulu dua kotak ketik bebas.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Package, Plus, RefreshCw, Search, CheckCircle2, Loader2, MoreHorizontal, Printer, Truck, Brain, MapPin, FileSpreadsheet,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { toast } from 'sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
// FASE H-5 — gulungan LAHIR dari penerimaan kain; layar ini juga menutup lubang
// penerimaan lama yang belum punya gulungan (backfill).
import RollLinesEditor from './warehouse/RollLinesEditor';
import RollImportPopup from './warehouse/RollImportPopup';
import RollPutawayPopup from './warehouse/RollPutawayPopup';
import { rollLinesState, fmtQty } from './warehouse/rollLines';

// Satuan roll ADA DI DATANYA (`uom`) — layar tidak boleh menebak "meter" dari
// nama field warisan `length_m`/`remaining_m`. Keluhan pemilik (2026-08-21):
// kain dibeli YARD tetapi tabel menulis "(m)", sehingga angka gulungan terlihat
// tidak cocok dengan PO padahal tidak ada konversi yang terjadi.
const rollUom = (r) => (r?.uom || '').toLowerCase() || 'satuan';
const rollTotal = (r) => Number(r?.qty_total ?? (r?.is_weight ? r?.weight_kg : r?.length_m) ?? 0);
const rollRemaining = (r) => Number(r?.qty_remaining ?? (r?.is_weight ? r?.remaining_kg : r?.remaining_m) ?? 0);

const API = process.env.REACT_APP_BACKEND_URL;

const QC_STATUS = {
  pending: { label: 'Menunggu QC', tone: 'warning' },
  pass: { label: 'Lolos', tone: 'success' },
  partial: { label: 'Sebagian', tone: 'primary' },
  reject: { label: 'Ditolak', tone: 'danger' },
};

const STOCK_STATUS = {
  in_stock: { label: 'Tersedia', tone: 'success' },
  partly_issued: { label: 'Sebagian terpakai', tone: 'primary' },
  fully_issued: { label: 'Habis', tone: 'muted' },
  returned: { label: 'Dikembalikan', tone: 'primary' },
  rejected: { label: 'Ditolak', tone: 'danger' },
  // 2026-11-09: roll impor stok awal — menunggu persetujuan Keuangan (belum bisa dipotong) / dibatalkan
  pending_opening: { label: 'Menunggu persetujuan stok awal', tone: 'warning' },
  cancelled: { label: 'Dibatalkan', tone: 'muted' },
};
// Jenis pergerakan roll (core/fabric_roll_engine) dalam bahasa staf
const GERAK = {
  receive: 'Diterima', putaway: 'Disimpan ke posisi', issue: 'Dikeluarkan', return: 'Dikembalikan',
  adjust: 'Penyesuaian', reject: 'Ditolak QC',
};
const qcLabel = (s) => QC_STATUS[s]?.label || s || '—';
const stokLabel = (s) => STOCK_STATUS[s]?.label || s || '—';
const Lencana = ({ peta, nilai }) => (
  <StatusBadge status={nilai} label={peta[nilai]?.label || nilai || '—'} tone={peta[nilai]?.tone || 'default'} />
);

const fmt = (n) => new Intl.NumberFormat('id-ID', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n ?? 0);
const fmtTgl = (d) => (d ? new Date(d).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }) : '—');

// Pilihan urutan (dulu tombol di kepala kolom). Bawaan: SISA paling sedikit di atas — roll yang hampir
// habis adalah yang paling perlu dilihat gudang (dan paling sering dicari pembelian).
const URUTAN = [
  ['qty_remaining:asc', 'Sisa paling sedikit'], ['qty_remaining:desc', 'Sisa terbanyak'],
  ['roll_no:asc', 'No. roll'], ['material_name:asc', 'Material A–Z'], ['supplier_name:asc', 'Supplier A–Z'],
  ['qc_status:asc', 'Status QC'], ['status:asc', 'Status stok'], ['position_barcode:asc', 'Posisi'],
];
const TAB = [
  { key: 'all', label: 'Semua' }, { key: 'in_stock', label: 'Tersedia' },
  { key: 'partly_issued', label: 'Sebagian terpakai' }, { key: 'fully_issued', label: 'Habis' },
  { key: 'pending_opening', label: 'Menunggu stok awal' },
];

export default function WMSFabricRollsModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [rolls, setRolls] = useState([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('all');
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState({ qc_status: 'all', status: '' });
  const [sort, setSort] = useState({ key: 'qty_remaining', dir: 'asc' });
  const [viewDialog, setViewDialog] = useState(null); // {roll, movements}
  const [issueDialog, setIssueDialog] = useState(null); // roll
  const [issueForm, setIssueForm] = useState({ qty: '', reference_type: 'wo', reference_no: '', notes: '' });
  const [putawayDialog, setPutawayDialog] = useState(null); // roll → RollPutawayPopup (posisi dari master / scan)
  const [formErr, setFormErr] = useState('');
  const [saving, setSaving] = useState(false);
  const [aiAnalysisDialog, setAiAnalysisDialog] = useState(null); // AI insights
  const [aiLoading, setAiLoading] = useState(false);
  // ── FASE H-5 ───────────────────────────────────────────────────────────────
  // `missing` = baris penerimaan kain yang SUDAH masuk stok tetapi belum punya
  // gulungan. Portal Cutting (H-6) MENOLAK memotong kain yang tidak punya gulungan,
  // jadi daftar ini adalah daftar pekerjaan yang menahan bagian potong.
  // `rollPolicy` dipakai untuk memberi tahu nomor berikutnya — nomor roll tidak pernah diketik.
  const [missing, setMissing] = useState([]);
  const [missingTotal, setMissingTotal] = useState(0);
  const [missingLoading, setMissingLoading] = useState(false);
  const [rollPolicy, setRollPolicy] = useState(null);
  const [issueRollsDialog, setIssueRollsDialog] = useState(null); // {row, lines}
  const [importDialog, setImportDialog] = useState(false);   // 2026-11-09: impor roll stok awal
  const [issuing, setIssuing] = useState(false);

  // Semua halaman dimuat (server membatasi 200 per permintaan; dulu hanya halaman pertama 50 roll).
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      if (filters.qc_status && filters.qc_status !== 'all') params.set('qc_status', filters.qc_status);
      if (filters.status) params.set('status', filters.status);
      if (tab !== 'all' && tab !== 'missing') params.set('status', tab);
      params.set('limit', '200');
      const semua = [];
      for (let page = 1; page <= 50; page += 1) {
        params.set('page', String(page));
        const r = await fetch(`${API}/api/wms/fabric-rolls?${params}`, { headers });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        semua.push(...(d.items || []));
        if (!d.pagination?.has_next) break;
      }
      setRolls(semua);
    } catch {
      toast.error('Gagal memuat data roll');
    } finally {
      setLoading(false);
    }
  }, [headers, search, filters, tab]);

  useEffect(() => { load(); }, [load]);

  // FASE H-5: daftar penerimaan kain tanpa gulungan + kebijakan nomor roll.
  const loadMissing = useCallback(async () => {
    setMissingLoading(true);
    try {
      const r = await fetch(`${API}/api/wms/fabric-rolls/missing-from-receipts?limit=100`, { headers });
      const d = await r.json();
      setMissing(d.items || []);
      setMissingTotal(Number(d.total ?? (d.items || []).length) || 0);
    } catch {
      toast.error('Gagal memuat daftar penerimaan tanpa roll');
    } finally {
      setMissingLoading(false);
    }
  }, [headers]);

  useEffect(() => { loadMissing(); }, [loadMissing]);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/api/wms/fabric-rolls/number-policy`, { headers });
        if (r.ok) setRollPolicy(await r.json());
      } catch { /* petunjuk nomor gagal diambil — layar tetap jalan */ }
    })();
  }, [headers]);

  const openIssueRolls = (row) => setIssueRollsDialog({
    row,
    lines: [{ qty: row.accepted_qty, color_lot: '', notes: '' }],
  });

  const submitIssueRolls = async () => {
    if (!issueRollsDialog) return;
    const { row, lines } = issueRollsDialog;
    const st = rollLinesState(lines, row.accepted_qty);
    if (st.state !== 'match') {
      toast.error(`Total gulungan ${fmtQty(st.total)} ${row.unit} belum sama dengan qty diterima `
        + `${fmtQty(row.accepted_qty)} ${row.unit}. Perbaiki angkanya dulu.`);
      return;
    }
    setIssuing(true);
    try {
      const r = await fetch(`${API}/api/wms/fabric-rolls/issue-from-receipt`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          receipt_id: row.receipt_id,
          item_id: row.item_id,
          lines: lines.filter(l => parseFloat(l.qty) > 0)
            .map(l => ({ qty: parseFloat(l.qty), color_lot: l.color_lot || '', notes: l.notes || '' })),
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      toast.success(d.message || `${(d.roll_numbers || []).length} gulungan diterbitkan`, { duration: 7000 });
      setIssueRollsDialog(null);
      await Promise.all([load(), loadMissing()]);
    } catch (e) {
      toast.error(e.message, { duration: 9000 });
    } finally {
      setIssuing(false);
    }
  };

  // 2026-11-02 (Paket 3a): label roll (Code128 = nomor roll). PDF diambil dengan header Authorization
  // (bukan token sesi di URL) lalu dibuka di tab baru.
  const printRollLabel = async (roll) => {
    try {
      const r = await fetch(`${API}/api/wms/fabric-rolls/${roll.id}/label-pdf`, { headers: { Authorization: headers.Authorization } });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${r.status}`);
      }
      const url = URL.createObjectURL(await r.blob());
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      toast.error(`Gagal mencetak label roll: ${e.message || e}`);
    }
  };

  const handleView = async (roll) => {
    try {
      const r = await fetch(`${API}/api/wms/fabric-rolls/${roll.id}`, { headers });
      const d = await r.json();
      // Endpoint mengembalikan dokumen roll (spread) + `movements`.
      setViewDialog({ roll: d, movements: d.movements || [] });
    } catch {
      toast.error('Gagal memuat detail roll');
    }
  };

  const bukaPutaway = (roll) => setPutawayDialog(roll);
  const bukaIssue = (roll) => { setFormErr(''); setIssueForm({ qty: '', reference_type: 'wo', reference_no: '', notes: '' }); setIssueDialog(roll); };

  const handleIssue = async () => {
    if (!(parseFloat(issueForm.qty) > 0)) { setFormErr('Qty wajib diisi.'); return; }
    setSaving(true); setFormErr('');
    try {
      const r = await fetch(`${API}/api/wms/fabric-rolls/${issueDialog.id}/issue`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          qty: parseFloat(issueForm.qty),
          unit: rollUom(issueDialog),
          reference_type: issueForm.reference_type || 'wo',
          reference_no: issueForm.reference_no || '',
          notes: issueForm.notes || '',
        }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || d.error || `HTTP ${r.status}`);
      }
      toast.success('Roll berhasil dikeluarkan');
      setIssueDialog(null);
      load();
    } catch (err) {
      toast.error(`Gagal mengeluarkan roll: ${err.message || err}`);
    } finally {
      setSaving(false);
    }
  };

  const handleAIAnalysis = async () => {
    setAiLoading(true);
    try {
      const rejectedRolls = rolls.filter(r => r.qc_status === 'reject' || r.qc_status === 'partial');
      const rollIds = rejectedRolls.map(r => r.id);

      const r = await fetch(`${API}/api/wms/ai/fabric-rolls/quality-analysis`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          roll_ids: rollIds,
          time_period_days: 30
        }),
      });

      if (!r.ok) throw new Error();
      const data = await r.json();
      setAiAnalysisDialog(data);
      toast.success('Analisis AI selesai');
    } catch (e) {
      toast.error('Gagal melakukan analisis AI');
      console.error(e);
    } finally {
      setAiLoading(false);
    }
  };

  const filteredRolls = useMemo(() => {
    if (tab === 'all') return rolls;
    return rolls.filter(r => r.status === tab);
  }, [rolls, tab]);

  // F13 — urutan & unduhan atas baris YANG TERLIHAT (semua halaman hasil saringan).
  const sortedRolls = useMemo(() => {
    const list = [...filteredRolls];
    const { key, dir } = sort;
    list.sort((a, b) => {
      const num = ['qty_total', 'qty_remaining', 'length_m', 'remaining_m',
        'weight_kg', 'remaining_kg'].includes(key);
      const av = key === 'qty_remaining' ? rollRemaining(a) : key === 'qty_total' ? rollTotal(a) : a?.[key];
      const bv = key === 'qty_remaining' ? rollRemaining(b) : key === 'qty_total' ? rollTotal(b) : b?.[key];
      const cmp = num ? (Number(av || 0) - Number(bv || 0))
        : String(av ?? '').localeCompare(String(bv ?? ''), 'id');
      return dir === 'asc' ? cmp : -cmp;
    });
    return list;
  }, [filteredRolls, sort]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(sortedRolls, 25);
  // Ringkasan sisa dikelompokkan PER SATUAN — menjumlahkan yard dengan kg adalah angka yang tidak berarti apa pun.
  const remainingBySatuan = useMemo(() => {
    const acc = {};
    sortedRolls.forEach((r) => {
      const u = rollUom(r);
      acc[u] = (acc[u] || 0) + rollRemaining(r);
    });
    return Object.entries(acc).map(([u, v]) => `${fmt(v)} ${u}`).join(' · ');
  }, [sortedRolls]);

  const tabMissing = tab === 'missing';

  const aksiRoll = (roll) => (
    <div className="flex items-center justify-end gap-1.5">
      <Button size="sm" variant="outline" onClick={() => bukaPutaway(roll)} data-testid={`putaway-btn-${roll.roll_no}`}>
        <MapPin />Simpan ke posisi
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="outline" aria-label="Aksi lainnya" title="Aksi lainnya" data-testid={`roll-more-${roll.roll_no}`}>
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem disabled={roll.status === 'fully_issued'} onSelect={() => bukaIssue(roll)} data-testid={`issue-btn-${roll.roll_no}`}>
            <Truck className="mr-2 h-4 w-4" />Keluarkan roll
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => printRollLabel(roll)} data-testid={`label-btn-${roll.roll_no}`}>
            <Printer className="mr-2 h-4 w-4" />Cetak label barcode
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );

  const kolomRoll = [
    { kunci: 'no', label: 'No. roll', hp: 'judul', isi: (r) => <span className="font-medium tabular-nums" data-testid={`roll-row-${r.roll_no}`}>{r.roll_no}</span> },
    { kunci: 'material', label: 'Material', hp: 'keterangan', isi: (r) => (
      <span>{r.material_name}{r.material_code && <span className="ml-1 text-muted-foreground">({r.material_code})</span>}</span>) },
    { kunci: 'warna', label: 'Warna / lot', hp: false, isi: (r) => <span className="whitespace-nowrap">{r.color || '—'} / {r.color_lot || '—'}</span> },
    { kunci: 'supplier', label: 'Supplier', hp: false, isi: (r) => r.supplier_name || '—' },
    { kunci: 'qc', label: 'QC', hp: false, isi: (r) => <Lencana peta={QC_STATUS} nilai={r.qc_status} /> },
    { kunci: 'stok', label: 'Status stok', isi: (r) => <Lencana peta={STOCK_STATUS} nilai={r.status} /> },
    { kunci: 'sisa', label: 'Sisa / total', rata: 'kanan', isi: (r) => (
      <span className="whitespace-nowrap tabular-nums" data-testid={`roll-qty-${r.roll_no}`}>
        {fmt(rollRemaining(r))} / {fmt(rollTotal(r))} <span data-testid={`roll-uom-${r.roll_no}`}>{rollUom(r)}</span>
        {r.qty_remaining_m != null && (
          <span className="block text-xs text-muted-foreground">≈ {fmt(r.qty_remaining_m)} / {fmt(r.qty_total_m)} m</span>
        )}
      </span>) },
    { kunci: 'posisi', label: 'Posisi', isi: (r) => (r.position_barcode
      ? <span className="tabular-nums">{r.position_barcode}</span>
      : <span className="text-[hsl(var(--warning-text))]">Belum disimpan ke posisi</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: aksiRoll },
  ];

  const kolomMissing = [
    { kunci: 'gr', label: 'No. penerimaan', hp: 'judul', isi: (m) => <span className="tabular-nums" data-testid={`missing-row-${m.material_code}`}>{m.receipt_number}</span> },
    { kunci: 'supplier', label: 'Supplier', hp: 'keterangan', isi: (m) => m.supplier_name || '-' },
    { kunci: 'kode', label: 'Kode kain', hp: false, isi: (m) => <span className="tabular-nums">{m.material_code}</span> },
    { kunci: 'nama', label: 'Nama kain', isi: (m) => m.material_name },
    { kunci: 'qty', label: 'Qty diterima', rata: 'kanan', isi: (m) => <span className="whitespace-nowrap tabular-nums"><strong>{fmtQty(m.accepted_qty)}</strong> {m.unit}</span> },
    { kunci: 'lokasi', label: 'Lokasi', hp: false, isi: (m) => m.location_name || '-' },
    { kunci: 'tgl', label: 'Tanggal', hp: false, isi: (m) => <span className="whitespace-nowrap">{fmtTgl(m.created_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (m) => (
      <Button size="sm" onClick={() => openIssueRolls(m)} data-testid={`issue-rolls-btn-${m.material_code}`}>
        <Plus />Terbitkan roll
      </Button>) },
  ];

  const tabOpsi = [...TAB, { key: 'missing', label: 'Penerimaan tanpa roll', count: missingTotal }];

  return (
    <PageLayout
      testId="wms-fabric-rolls-module"
      title="Roll Kain"
      subtitle="Stok kain per gulungan: sisa, status QC, posisi rak, dan label barcode."
      actions={(
        <>
          <Button variant="outline" onClick={handleAIAnalysis} disabled={aiLoading} data-testid="ai-analysis-btn">
            {aiLoading ? <Loader2 className="animate-spin" /> : <Brain />}
            Analisis AI
          </Button>
          <Button variant="outline" onClick={() => setImportDialog(true)} data-testid="import-roll-btn">
            <FileSpreadsheet />Impor roll
          </Button>
        </>
      )}
      filters={<>
        {(
        <>
          <FilterChips className="w-full sm:w-auto" options={tabOpsi} value={tab} onChange={setTab} hideWhenEmpty={false} testId="rolls-tab" />
          {!tabMissing && (
            <>
              <div className="relative w-full sm:w-64">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input placeholder="Cari no. roll, material, warna, supplier" value={search}
                  onChange={(e) => setSearch(e.target.value)} className="pl-8" data-testid="search-roll-input" />
              </div>
              <SmartNativeSelect value={filters.qc_status} onChange={(e) => setFilters({ ...filters, qc_status: e.target.value })}
                className="w-full sm:w-40" wrapperClassName="w-full sm:w-40" aria-label="Status QC" data-testid="qc-filter">
                <option value="all">Semua QC</option>
                {Object.entries(QC_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </SmartNativeSelect>
              <SmartNativeSelect value={`${sort.key}:${sort.dir}`} aria-label="Urutkan"
                onChange={(e) => { const [key, dir] = e.target.value.split(':'); setSort({ key, dir }); }}
                className="w-full sm:w-48" wrapperClassName="w-full sm:w-48" data-testid="rolls-sort">
                {URUTAN.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </SmartNativeSelect>
            </>
          )}
        </>
      )}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {tabMissing ? (
        <>
          <TombolUnduh namaBerkas="penerimaan-kain-tanpa-roll" namaLembar="Tanpa roll" baris={missing} testId="missing-unduh"
            kolom={[
              { label: 'No. penerimaan', nilai: (m) => m.receipt_number },
              { label: 'Supplier', nilai: (m) => m.supplier_name || '' },
              { label: 'Kode kain', nilai: (m) => m.material_code },
              { label: 'Nama kain', nilai: (m) => m.material_name },
              { label: 'Qty diterima', nilai: (m) => Number(m.accepted_qty || 0) },
              { label: 'Satuan', nilai: (m) => m.unit },
              { label: 'Lokasi', nilai: (m) => m.location_name || '' },
              { label: 'Tanggal', nilai: (m) => fmtTgl(m.created_at) },
            ]} />
          <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={loadMissing} disabled={missingLoading}
            data-testid="refresh-missing-btn">
            <RefreshCw className={missingLoading ? 'animate-spin' : ''} />
          </Button>
        </>
      ) : (
        <>
          <TombolUnduh namaBerkas="stok-kain-per-roll" namaLembar="Roll kain" baris={sortedRolls} testId="rolls-unduh"
            kolom={[
              { label: 'No. roll', nilai: (r) => r.roll_no },
              { label: 'Kode material', nilai: (r) => r.material_code },
              { label: 'Material', nilai: (r) => r.material_name },
              { label: 'Warna', nilai: (r) => r.color },
              { label: 'Lot', nilai: (r) => r.color_lot },
              { label: 'Supplier', nilai: (r) => r.supplier_name },
              { label: 'No. PO', nilai: (r) => r.po_no },
              { label: 'Status QC', nilai: (r) => qcLabel(r.qc_status) },
              { label: 'Status stok', nilai: (r) => stokLabel(r.status) },
              { label: 'Satuan', nilai: (r) => rollUom(r) },
              { label: 'Total', nilai: (r) => rollTotal(r) },
              { label: 'Sisa', nilai: (r) => rollRemaining(r) },
              { label: '≈ Total (m)', nilai: (r) => r.qty_total_m ?? '' },
              { label: '≈ Sisa (m)', nilai: (r) => r.qty_remaining_m ?? '' },
              { label: 'Posisi', nilai: (r) => r.position_barcode || '' },
            ]} />
          <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={load} disabled={loading}
            data-testid="refresh-rolls-btn">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </>
      )}
        </div>
      </>}
      summary={!tabMissing && sortedRolls.length > 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="rolls-summary">
          {sortedRolls.length} roll sesuai saringan · sisa kain: <span className="font-medium text-foreground">{remainingBySatuan}</span>
        </p>
      ) : null}
      footer={!tabMissing && total > 0 ? (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      ) : null}
    >
      {tabMissing ? (
        /* ── FASE H-5: penerimaan kain yang belum punya gulungan ─────────────
           Kain yang ada di stok tetapi tidak punya gulungan akan MENGHENTIKAN Portal Cutting (H-6). */
        <div className="space-y-3" data-testid="missing-rolls-panel">
          <p className="text-sm text-muted-foreground">
            Kain yang <strong className="text-foreground">sudah masuk stok</strong> lewat Penerimaan Barang tetapi belum punya
            satu pun gulungan. Portal Cutting menolak memotong kain tanpa gulungan — terbitkan gulungannya di sini (nomor
            otomatis{rollPolicy?.next_number ? `, berikutnya ${rollPolicy.next_number}` : ''}).
            {missingTotal > missing.length && ` Menampilkan ${missing.length} dari ${missingTotal} baris.`}
          </p>
          {missingLoading && missing.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Memuat…</p>
          ) : (
            <TabelData kolom={kolomMissing} baris={missing} kunci={(m) => m.item_id} testId="missing-rolls-table"
              kosong={<EmptyState icon={CheckCircle2} testId="missing-rolls-empty"
                title="Semua penerimaan kain sudah punya gulungan"
                description="Tidak ada kain yang menahan bagian potong. Gulungan baru lahir sendiri dari Penerimaan Barang berikutnya." />} />
          )}
        </div>
      ) : loading && rolls.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground" data-testid="loading-rolls">Memuat roll…</p>
      ) : (
        <TabelData kolom={kolomRoll} baris={paged} onKlikBaris={handleView} testId="rolls-table"
          kosong={<EmptyState icon={Package} testId="rolls-empty"
            title={search ? 'Tidak ada hasil pencarian' : 'Belum ada data roll'}
            description={search
              ? `Tidak ditemukan roll dengan kata kunci "${search}".`
              : 'Roll tidak dibuat manual — roll lahir dari Penerimaan Barang (isi rincian gulungan pada baris kain), dari tab "Penerimaan tanpa roll" untuk penerimaan yang sudah lewat, atau dari Impor roll stok awal untuk kain yang sudah ada di gudang.'}
            action={search ? undefined : (missingTotal > 0
              ? { label: 'Lihat penerimaan tanpa roll', onClick: () => setTab('missing') }
              : { label: 'Impor roll stok awal', onClick: () => setImportDialog(true), icon: FileSpreadsheet })} />} />
      )}

      <RollImportPopup open={importDialog} onClose={() => setImportDialog(false)} onDone={() => load()} />

      {/* ── FASE H-5: terbitkan gulungan untuk penerimaan yang sudah lewat ───── */}
      {issueRollsDialog && (
        <FormPopup open onClose={() => setIssueRollsDialog(null)} ukuran="panjang" testId="issue-rolls-dialog"
          judul={`Terbitkan gulungan — ${issueRollsDialog.row.material_code}`}
          keterangan={`${issueRollsDialog.row.receipt_number} · ${issueRollsDialog.row.supplier_name || '-'} · ${issueRollsDialog.row.material_name}`}
          onSimpan={submitIssueRolls} menyimpan={issuing} labelSimpan="Terbitkan gulungan">
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Qty diterima">
              <span className="font-medium tabular-nums">{fmtQty(issueRollsDialog.row.accepted_qty)} {issueRollsDialog.row.unit}</span>
            </BarisDetail>
          </dl>
          <RollLinesEditor
            lines={issueRollsDialog.lines}
            accepted={issueRollsDialog.row.accepted_qty}
            unit={issueRollsDialog.row.unit}
            onChange={(lines) => setIssueRollsDialog((d) => ({ ...d, lines }))}
            testPrefix="backfill-roll-lines"
            nextNumberHint={rollPolicy?.next_number || ''}
            title="Rincian gulungan (retroaktif)"
            subtitle={`Timbang/ukur gulungan yang ada di rak sekarang. Totalnya harus sama dengan qty yang dulu diterima (${fmtQty(issueRollsDialog.row.accepted_qty)} ${issueRollsDialog.row.unit}) — gulungan dan stok harus menjelaskan penerimaan yang sama.`}
          />
        </FormPopup>
      )}

      {/* ── Detail roll ───────────────────────────────────────────────────────── */}
      {viewDialog && (
        <DetailPopup open onClose={() => setViewDialog(null)} testId="view-roll-dialog"
          judul={`Roll ${viewDialog.roll?.roll_no || ''}`}
          status={<><Lencana peta={QC_STATUS} nilai={viewDialog.roll?.qc_status} /><Lencana peta={STOCK_STATUS} nilai={viewDialog.roll?.status} /></>}
          aksi={viewDialog.roll?.id ? (
            <>
              <Button size="sm" variant="outline" onClick={() => { const r = viewDialog.roll; setViewDialog(null); bukaPutaway(r); }}>
                <MapPin />Simpan ke posisi
              </Button>
              <Button size="sm" variant="outline" disabled={viewDialog.roll.status === 'fully_issued'}
                onClick={() => { const r = viewDialog.roll; setViewDialog(null); bukaIssue(r); }}>
                <Truck />Keluarkan
              </Button>
              <Button size="sm" variant="outline" onClick={() => printRollLabel(viewDialog.roll)}>
                <Printer />Cetak label
              </Button>
            </>
          ) : null}>
          <dl className="grid gap-x-6 sm:grid-cols-2">
            <BarisDetail label="Material">{viewDialog.roll?.material_name || '—'}</BarisDetail>
            <BarisDetail label="Warna / lot">{viewDialog.roll?.color || '-'} / {viewDialog.roll?.color_lot || '-'}</BarisDetail>
            <BarisDetail label="Supplier">{viewDialog.roll?.supplier_name || '-'}</BarisDetail>
            <BarisDetail label="No. PO">{viewDialog.roll?.po_no || '-'}</BarisDetail>
            <BarisDetail label="Sisa / total">
              <span className="tabular-nums" data-testid="roll-detail-qty">
                {fmt(rollRemaining(viewDialog.roll))} / {fmt(rollTotal(viewDialog.roll))} {rollUom(viewDialog.roll)}
                {viewDialog.roll?.qty_remaining_m != null && (
                  <span className="block text-xs text-muted-foreground">
                    ≈ {fmt(viewDialog.roll.qty_remaining_m)} / {fmt(viewDialog.roll.qty_total_m)} m
                  </span>
                )}
              </span>
            </BarisDetail>
            {!viewDialog.roll?.is_weight && viewDialog.roll?.weight_kg > 0 && (
              <BarisDetail label="Berat">{fmt(viewDialog.roll.remaining_kg)} / {fmt(viewDialog.roll.weight_kg)} kg</BarisDetail>
            )}
            {viewDialog.roll?.location_name && <BarisDetail label="Lokasi gudang">{viewDialog.roll.location_name}</BarisDetail>}
            <BarisDetail label="Posisi">{viewDialog.roll?.position_barcode || 'Belum disimpan ke posisi'}</BarisDetail>
            {/* FASE H-5: asal gulungan — jejak balik ke penerimaan / impor stok awal yang melahirkannya */}
            <BarisDetail label="Asal gulungan">
              {viewDialog.roll?.source_receipt_number
                ? <span className="tabular-nums">Penerimaan {viewDialog.roll.source_receipt_number}</span>
                : viewDialog.roll?.opening_import_no
                  ? <span className="tabular-nums">Impor stok awal {viewDialog.roll.opening_import_no}</span>
                  : 'Dibuat manual (jalur lama, sudah ditutup)'}
            </BarisDetail>
          </dl>
          <div>
            <p className="mb-2 text-sm font-medium text-foreground">Riwayat pergerakan</p>
            {!viewDialog.movements?.length ? (
              <p className="text-sm text-muted-foreground">Roll ini belum pernah bergerak sejak dibuat.</p>
            ) : (
              <div className="overflow-x-auto">
                <Table className="min-w-[32rem]">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Waktu</TableHead><TableHead>Jenis</TableHead>
                      <TableHead className="text-right">Qty</TableHead><TableHead>Catatan</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {viewDialog.movements.map((m, i) => (
                      <TableRow key={i}>
                        <TableCell className="whitespace-nowrap">{m.created_at ? new Date(m.created_at).toLocaleString('id-ID') : '—'}</TableCell>
                        <TableCell>{GERAK[m.movement_type] || m.movement_type}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmt(m.qty)} {m.unit}</TableCell>
                        <TableCell className="text-muted-foreground">{m.notes || '—'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        </DetailPopup>
      )}

      {/* ── Simpan roll ke posisi (put-away): posisi dari master struktur gudang atau scan barcode ── */}
      <RollPutawayPopup roll={putawayDialog} onClose={() => setPutawayDialog(null)} onDone={load} />

      {/* ── Keluarkan roll (issue) ────────────────────────────────────────────── */}
      {issueDialog && (
        <FormPopup open onClose={() => setIssueDialog(null)} ukuran="pendek" testId="issue-dialog"
          judul={`Keluarkan roll ${issueDialog.roll_no}`}
          keterangan={`Sisa ${fmt(rollRemaining(issueDialog))} ${rollUom(issueDialog)}.`}
          onSimpan={handleIssue} menyimpan={saving} galat={formErr} labelSimpan="Keluarkan">
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Qty" wajib htmlFor="iss-qty">
              <Input id="iss-qty" type="number" step="0.01" value={issueForm.qty}
                onChange={(e) => setIssueForm((f) => ({ ...f, qty: e.target.value }))} data-testid="input-issue-qty" />
            </Isian>
            {/* Gulungan hanya bisa dikeluarkan dalam satuannya sendiri — dulu pilihan meter/kg di sini
                membuat gulungan yard terkurangi dengan label yang salah. */}
            <Isian label="Satuan gulungan" htmlFor="iss-satuan">
              <Input id="iss-satuan" value={rollUom(issueDialog)} readOnly className="tabular-nums" data-testid="input-issue-unit" />
            </Isian>
          </div>
          <Isian label="Jenis referensi" htmlFor="iss-jenis">
            <SmartNativeSelect id="iss-jenis" value={issueForm.reference_type}
              onChange={(e) => setIssueForm((f) => ({ ...f, reference_type: e.target.value }))} data-testid="input-ref-type">
              <option value="wo">Perintah kerja (WO)</option>
              <option value="cmt">CMT</option>
              <option value="manual">Manual</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="No. referensi" htmlFor="iss-ref">
            <Input id="iss-ref" value={issueForm.reference_no}
              onChange={(e) => setIssueForm((f) => ({ ...f, reference_no: e.target.value }))} data-testid="input-ref-no" />
          </Isian>
          <Isian label="Catatan" htmlFor="iss-catatan">
            <Input id="iss-catatan" value={issueForm.notes}
              onChange={(e) => setIssueForm((f) => ({ ...f, notes: e.target.value }))} data-testid="input-issue-notes" />
          </Isian>
        </FormPopup>
      )}

      {/* ── Hasil analisis AI ─────────────────────────────────────────────────── */}
      {aiAnalysisDialog && (
        <DetailPopup open onClose={() => setAiAnalysisDialog(null)} testId="ai-analysis-dialog"
          judul="Analisis pola kualitas kain (AI)"
          keterangan="Dibuat AI dari roll berstatus QC ditolak atau sebagian. Periksa ulang sebelum dipakai untuk keputusan.">
          {aiAnalysisDialog.data_summary && (
            <dl className="divide-y divide-[var(--glass-border)]">
              {/* Angka dihitung server dari roll ber-QC "ditolak/sebagian" (services/ai_aggregates/wms_aggregates.py).
                  "Periode 30 hari" dulu ditampilkan sebagai kartu, padahal hitungannya TIDAK dibatasi tanggal — disembunyikan. */}
              <BarisDetail label="Roll QC ditolak / sebagian">{aiAnalysisDialog.data_summary.total_rejections ?? '—'}</BarisDetail>
              <BarisDetail label="Pemasok terdampak">{aiAnalysisDialog.data_summary.affected_suppliers ?? '—'}</BarisDetail>
            </dl>
          )}
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{aiAnalysisDialog.analysis}</div>
          {aiAnalysisDialog.generated_at && (
            <p className="text-xs text-muted-foreground">Dibuat {new Date(aiAnalysisDialog.generated_at).toLocaleString('id-ID')}</p>
          )}
        </DetailPopup>
      )}
    </PageLayout>
  );
}

/**
 * Roll Kain — stok kain per gulungan (barcode, status QC, posisi).
 * P0-WH-1: Fabric roll tracking dengan barcode, QC status, position management.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (dulu kepala bergradien "Fabric Roll Tracking" dengan ikon,
 * tab bar abu, tampilan kartu besar); tab status → pil penyaring; daftar = TabelData dengan pilihan urutan dan
 * unduhan Excel + CSV; aksi baris maks 2 (sisanya "Lainnya"); semua form (roll baru, simpan ke posisi, keluarkan,
 * terbitkan gulungan) = FormPopup; detail roll & hasil analisis AI = DetailPopup.
 * Perbaikan ikut: daftar dulu hanya memuat 50 roll pertama (bawaan server) lalu diurutkan/diunduh/dijumlah
 * seolah-olah semua — kini semua halaman dimuat (200 per permintaan).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Package, Plus, RefreshCw, Search, CheckCircle2, Loader2, MoreHorizontal, Printer, Truck, Brain, MapPin,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
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
import { materialOptionLabel } from '@/lib/materialFields';
import { toast } from 'sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
// FASE H-5 — gulungan LAHIR dari penerimaan kain; layar ini juga menutup lubang
// penerimaan lama yang belum punya gulungan (backfill).
import RollLinesEditor from './warehouse/RollLinesEditor';
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
];
const ROLL_BARU = { color_lot: '', uom: 'meter', length_m: '0', weight_kg: '0', notes: '' };

export default function WMSFabricRollsModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [rolls, setRolls] = useState([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('all');
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState({ qc_status: 'all', status: '' });
  const [sort, setSort] = useState({ key: 'qty_remaining', dir: 'asc' });
  const [viewDialog, setViewDialog] = useState(null); // {roll, movements}
  const [createDialog, setCreateDialog] = useState(false);
  // Unit cost dialog Buat Roll = MoneyInput terkendali (teks tampilannya bertitik ribuan).
  // Kembali ke 0 setiap dialog dibuka.
  const [createUnitCost, setCreateUnitCost] = useState('0');
  // 2026-11-07 (Tahap 5): roll baru menunjuk MASTER — material kain, supplier, dan PO dipilih dari daftar.
  // Dulu semua teks bebas dan `material_id` tidak pernah terisi (form tidak punya isiannya), sehingga roll
  // manual tidak pernah tertaut ke material: tidak ikut stok/HPP per kain dan tidak bisa dipakai Cutting.
  const [createPick, setCreatePick] = useState({ material_id: '', supplier_name: '', po_no: '', color: '' });
  const [createForm, setCreateForm] = useState(ROLL_BARU);
  const [rollMasters, setRollMasters] = useState({ materials: [], suppliers: [], pos: [], loaded: false });
  useEffect(() => { if (createDialog) { setCreateUnitCost('0'); setCreateForm(ROLL_BARU); } }, [createDialog]);
  const [issueDialog, setIssueDialog] = useState(null); // roll
  const [issueForm, setIssueForm] = useState({ qty: '', reference_type: 'wo', reference_no: '', notes: '' });
  const [putawayDialog, setPutawayDialog] = useState(null); // roll
  const [putawayForm, setPutawayForm] = useState({ position_id: '', position_barcode: '', notes: '' });
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
    } catch (e) {
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

  useEffect(() => {
    if (!createDialog || rollMasters.loaded) return undefined;
    let alive = true;
    const get = (u) => fetch(`${API}${u}`, { headers }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    Promise.all([
      get('/api/rahaza/materials?type=bahan'),
      get('/api/procurement/suppliers/options'),
      get('/api/rahaza/purchase-orders?status=approved'),
      get('/api/rahaza/purchase-orders?status=partially_received'),
      get('/api/rahaza/purchase-orders?status=fully_received'),
    ]).then(([m, s, a, b, c]) => {
      if (!alive) return;
      const list = (x) => (Array.isArray(x) ? x : (x?.items || []));
      setRollMasters({
        materials: list(m).filter((x) => x.type === 'fabric' || x.type === 'kain'),
        suppliers: s?.items || [],
        pos: [...list(a), ...list(b), ...list(c)],
        loaded: true,
      });
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createDialog]);
  const pickedMat = rollMasters.materials.find((m) => m.id === createPick.material_id) || null;

  const handleCreateRoll = async () => {
    if (!createPick.material_id) { toast.error('Pilih material kain dari master.'); return; }
    const data = {
      // FASE H-5: `roll_no` TIDAK dikirim — nomor diterbitkan server (mode otomatis).
      material_id: createPick.material_id,
      material_code: pickedMat?.code || '',
      material_name: pickedMat?.name || '',
      color: createPick.color || pickedMat?.color || '',
      color_lot: createForm.color_lot || '',
      supplier_name: createPick.supplier_name || '',
      uom: createForm.uom || 'meter',
      length_m: parseFloat(createForm.length_m) || 0,
      weight_kg: parseFloat(createForm.weight_kg) || 0,
      po_no: createPick.po_no || '',
      unit_cost: parseFloat(createUnitCost) || 0,
      notes: createForm.notes || '',
    };
    setSaving(true);
    try {
      const r = await fetch(`${API}/api/wms/fabric-rolls`, {
        method: 'POST',
        headers,
        body: JSON.stringify(data),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      toast.success(`Roll ${d?.roll?.roll_no || ''} dibuat`);
      setCreatePick({ material_id: '', supplier_name: '', po_no: '', color: '' });
      setCreateDialog(false);
      load();
    } catch (e2) {
      toast.error(e2.message || 'Gagal membuat roll', { duration: 8000 });
    } finally {
      setSaving(false);
    }
  };

  const bukaPutaway = (roll) => { setFormErr(''); setPutawayForm({ position_id: '', position_barcode: '', notes: '' }); setPutawayDialog(roll); };
  const bukaIssue = (roll) => { setFormErr(''); setIssueForm({ qty: '', reference_type: 'wo', reference_no: '', notes: '' }); setIssueDialog(roll); };

  const handlePutaway = async () => {
    if (!putawayForm.position_id.trim()) { setFormErr('ID posisi wajib diisi.'); return; }
    setSaving(true); setFormErr('');
    try {
      const r = await fetch(`${API}/api/wms/fabric-rolls/${putawayDialog.id}/putaway`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          position_id: putawayForm.position_id,
          position_barcode: putawayForm.position_barcode || '',
          notes: putawayForm.notes || '',
        }),
      });
      if (!r.ok) throw new Error();
      toast.success('Roll berhasil dipindahkan ke posisi');
      setPutawayDialog(null);
      load();
    } catch {
      toast.error('Gagal menyimpan roll ke posisi');
    } finally {
      setSaving(false);
    }
  };

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
    { kunci: 'warna', label: 'Warna / lot', isi: (r) => <span className="whitespace-nowrap">{r.color || '—'} / {r.color_lot || '—'}</span> },
    { kunci: 'supplier', label: 'Supplier', isi: (r) => r.supplier_name || '—' },
    { kunci: 'qc', label: 'QC', isi: (r) => <Lencana peta={QC_STATUS} nilai={r.qc_status} /> },
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
    { kunci: 'kode', label: 'Kode kain', isi: (m) => <span className="tabular-nums">{m.material_code}</span> },
    { kunci: 'nama', label: 'Nama kain', isi: (m) => m.material_name },
    { kunci: 'qty', label: 'Qty diterima', rata: 'kanan', isi: (m) => <span className="whitespace-nowrap tabular-nums"><strong>{fmtQty(m.accepted_qty)}</strong> {m.unit}</span> },
    { kunci: 'lokasi', label: 'Lokasi', isi: (m) => m.location_name || '-' },
    { kunci: 'tgl', label: 'Tanggal', isi: (m) => <span className="whitespace-nowrap">{fmtTgl(m.created_at)}</span> },
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
          <Button onClick={() => setCreateDialog(true)} data-testid="create-roll-btn">
            <Plus />Roll baru
          </Button>
        </>
      )}
      filters={(
        <>
          <FilterChips options={tabOpsi} value={tab} onChange={setTab} hideWhenEmpty={false} testId="rolls-tab" />
          {!tabMissing && (
            <>
              <div className="relative w-full sm:w-64">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input placeholder="Cari no. roll, material, warna, supplier" value={search}
                  onChange={(e) => setSearch(e.target.value)} className="pl-8" data-testid="search-roll-input" />
              </div>
              <SmartNativeSelect value={filters.qc_status} onChange={(e) => setFilters({ ...filters, qc_status: e.target.value })}
                className="w-full sm:w-40" aria-label="Status QC" data-testid="qc-filter">
                <option value="all">Semua QC</option>
                {Object.entries(QC_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </SmartNativeSelect>
              <SmartNativeSelect value={`${sort.key}:${sort.dir}`} aria-label="Urutkan"
                onChange={(e) => { const [key, dir] = e.target.value.split(':'); setSort({ key, dir }); }}
                className="w-full sm:w-48" data-testid="rolls-sort">
                {URUTAN.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </SmartNativeSelect>
            </>
          )}
        </>
      )}
      tools={tabMissing ? (
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
            <p className="py-10 text-center text-sm text-muted-foreground">Memuat…</p>
          ) : (
            <TabelData kolom={kolomMissing} baris={missing} kunci={(m) => m.item_id} testId="missing-rolls-table"
              kosong={<EmptyState icon={CheckCircle2} testId="missing-rolls-empty"
                title="Semua penerimaan kain sudah punya gulungan"
                description="Tidak ada kain yang menahan bagian potong. Gulungan baru lahir sendiri dari Penerimaan Barang berikutnya." />} />
          )}
        </div>
      ) : loading && rolls.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground" data-testid="loading-rolls">Memuat roll…</p>
      ) : (
        <TabelData kolom={kolomRoll} baris={paged} onKlikBaris={handleView} testId="rolls-table"
          kosong={<EmptyState icon={Package}
            title={search ? 'Tidak ada hasil pencarian' : 'Belum ada data roll'}
            description={search
              ? `Tidak ditemukan roll dengan kata kunci "${search}".`
              : 'Gulungan lahir otomatis dari Penerimaan Barang: isi "Rincian gulungan" pada baris kain, dan nomor roll diterbitkan sistem. Untuk penerimaan yang sudah lewat, buka "Penerimaan tanpa roll".'}
            action={{ label: 'Buat roll manual', onClick: () => setCreateDialog(true), icon: Plus }} />} />
      )}

      {/* ── Roll baru (manual) ───────────────────────────────────────────────── */}
      <FormPopup open={createDialog} onClose={() => setCreateDialog(false)} ukuran="panjang" testId="create-roll-dialog"
        judul="Roll baru"
        keterangan={`Nomor roll otomatis: ${rollPolicy?.next_number || 'RL-…'} (pola ${rollPolicy?.format || 'RL-{YYYY}{MM}-{SEQ:4}'}, diatur di Administrasi Sistem › Penomoran Dokumen).`}
        onSimpan={handleCreateRoll} menyimpan={saving} labelSimpan="Simpan">
        <span className="sr-only" data-testid="roll-no-auto">{rollPolicy?.next_number || 'RL-…'}</span>
        <Isian label="Material kain" wajib htmlFor="roll-material">
          <SmartNativeSelect id="roll-material" value={createPick.material_id}
            onChange={(e) => {
              const m = rollMasters.materials.find((x) => x.id === e.target.value);
              setCreatePick((p) => ({ ...p, material_id: e.target.value, color: m?.color || '' }));
            }}
            data-testid="input-material">
            <option value="">{rollMasters.loaded ? '— pilih kain dari master —' : 'Memuat material…'}</option>
            {rollMasters.materials.map((m) => <option key={m.id} value={m.id}>{materialOptionLabel(m)}</option>)}
          </SmartNativeSelect>
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Warna" htmlFor="roll-warna">
            <Input id="roll-warna" value={createPick.color} onChange={(e) => setCreatePick((p) => ({ ...p, color: e.target.value }))}
              placeholder={pickedMat?.color ? '' : 'mis. Navy'} data-testid="input-color" />
          </Isian>
          <Isian label="Lot warna" htmlFor="roll-lot">
            <Input id="roll-lot" value={createForm.color_lot} onChange={(e) => setCreateForm((f) => ({ ...f, color_lot: e.target.value }))}
              data-testid="input-color-lot" />
          </Isian>
          <Isian label="Supplier" htmlFor="roll-supplier">
            <SmartNativeSelect id="roll-supplier" value={createPick.supplier_name}
              onChange={(e) => setCreatePick((p) => ({ ...p, supplier_name: e.target.value }))}
              data-testid="input-supplier">
              <option value="">— tanpa supplier —</option>
              {rollMasters.suppliers.map((s) => <option key={s.id} value={s.name}>{`${s.code} — ${s.name}`}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="No. PO" htmlFor="roll-po">
            <SmartNativeSelect id="roll-po" value={createPick.po_no}
              onChange={(e) => {
                const po = rollMasters.pos.find((x) => x.po_number === e.target.value);
                setCreatePick((p) => ({ ...p, po_no: e.target.value,
                  supplier_name: po ? (po.supplier_name || po.vendor_name || p.supplier_name) : p.supplier_name }));
              }}
              data-testid="input-po-no">
              <option value="">— tanpa PO —</option>
              {rollMasters.pos.map((po) => <option key={po.id} value={po.po_number}>{`${po.po_number} · ${po.supplier_name || po.vendor_name || ''}`}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Satuan" htmlFor="roll-satuan">
            <SmartNativeSelect id="roll-satuan" value={createForm.uom} onChange={(e) => setCreateForm((f) => ({ ...f, uom: e.target.value }))}
              data-testid="input-uom">
              <option value="meter">Meter</option>
              <option value="yard">Yard</option>
              <option value="rol">Rol</option>
              <option value="gulung">Gulung</option>
              <option value="kg">Kilogram</option>
              <option value="bal">Bal</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="Panjang / jumlah (sesuai satuan)" htmlFor="roll-panjang">
            <Input id="roll-panjang" type="number" step="0.01" value={createForm.length_m}
              onChange={(e) => setCreateForm((f) => ({ ...f, length_m: e.target.value }))} data-testid="input-length" />
          </Isian>
          <Isian label="Berat (kg)" htmlFor="roll-berat">
            <Input id="roll-berat" type="number" step="0.01" value={createForm.weight_kg}
              onChange={(e) => setCreateForm((f) => ({ ...f, weight_kg: e.target.value }))} data-testid="input-weight" />
          </Isian>
          <Isian label="Harga per satuan (Rp)" htmlFor="roll-harga">
            <MoneyInput id="roll-harga" decimals={2} value={createUnitCost} onChange={(e) => setCreateUnitCost(e.target.value)} data-testid="input-unit-cost" />
          </Isian>
        </div>
        <Isian label="Catatan" htmlFor="roll-catatan">
          <Input id="roll-catatan" value={createForm.notes} onChange={(e) => setCreateForm((f) => ({ ...f, notes: e.target.value }))}
            data-testid="input-notes" />
        </Isian>
      </FormPopup>

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
            <BarisDetail label="Posisi">{viewDialog.roll?.position_barcode || 'Belum disimpan ke posisi'}</BarisDetail>
            {/* FASE H-5: asal gulungan — jejak balik ke penerimaan yang melahirkannya */}
            <BarisDetail label="Asal gulungan">
              {viewDialog.roll?.source_receipt_number
                ? <span className="tabular-nums">Penerimaan {viewDialog.roll.source_receipt_number}</span>
                : 'Dibuat manual di layar Roll Kain'}
            </BarisDetail>
          </dl>
          <div>
            <p className="mb-2 text-sm font-medium text-foreground">Riwayat pergerakan</p>
            {!viewDialog.movements?.length ? (
              <p className="text-sm text-muted-foreground">Belum ada pergerakan.</p>
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

      {/* ── Simpan roll ke posisi (put-away) ──────────────────────────────────── */}
      {putawayDialog && (
        <FormPopup open onClose={() => setPutawayDialog(null)} ukuran="pendek" testId="putaway-dialog"
          judul={`Simpan roll ${putawayDialog.roll_no} ke posisi`}
          onSimpan={handlePutaway} menyimpan={saving} galat={formErr} labelSimpan="Simpan">
          <Isian label="ID posisi" wajib htmlFor="pa-roll-posisi">
            <Input id="pa-roll-posisi" value={putawayForm.position_id}
              onChange={(e) => setPutawayForm((f) => ({ ...f, position_id: e.target.value }))} data-testid="input-position-id" />
          </Isian>
          <Isian label="Barcode posisi" htmlFor="pa-roll-barcode">
            <Input id="pa-roll-barcode" value={putawayForm.position_barcode}
              onChange={(e) => setPutawayForm((f) => ({ ...f, position_barcode: e.target.value }))} data-testid="input-position-barcode" />
          </Isian>
          <Isian label="Catatan" htmlFor="pa-roll-catatan">
            <Input id="pa-roll-catatan" value={putawayForm.notes}
              onChange={(e) => setPutawayForm((f) => ({ ...f, notes: e.target.value }))} data-testid="input-putaway-notes" />
          </Isian>
        </FormPopup>
      )}

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

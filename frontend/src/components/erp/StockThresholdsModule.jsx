import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  AlertTriangle, Search, RefreshCw, Save, Wand2, Info, Eraser, ShoppingCart, Layers,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const STATUS_META = {
  critical:     { label: 'Kritis',          tone: 'danger' },
  low:          { label: 'Perlu pesan',     tone: 'warning' },
  ok:           { label: 'Aman',            tone: 'success' },
  no_threshold: { label: 'Belum berambang', tone: 'muted' },
};
const JENIS_LABEL = {
  yarn: 'Bahan', fabric: 'Bahan', kain: 'Bahan', benang: 'Bahan', interlining: 'Bahan',
  accessory: 'Aksesoris', packaging: 'Aksesoris', fg: 'Produk jadi',
};
const jenisLabel = (t) => JENIS_LABEL[t] || 'Lainnya';

const num = (v) => (v === '' || v == null ? 0 : Number(v) || 0);
const fmt = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 });
const angka = (v) => Number(v || 0).toLocaleString('id-ID');

// Empat DASAR pengisian massal. Semuanya punya pijakan nyata; tidak ada yang menebak.
const MODES = [
  {
    key: 'purchase_lot',
    label: 'Dari lot pembelian',
    hint: 'rata-rata satu kali beli dari penerimaan nyata 12 bulan terakhir × pengali',
    param: { key: 'lot_multiplier', label: 'Pengali lot', def: '0.5', step: '0.1', suffix: '×' },
  },
  {
    key: 'usage_30d',
    label: 'Dari pemakaian 30 hari',
    hint: 'pakai per hari × masa tunggu pembelian — hanya untuk barang yang pernah dipakai',
    param: null,
  },
  {
    key: 'percent_onhand',
    label: 'Persen stok sekarang',
    hint: 'stok sekarang dianggap normal; ambang = sebagian dari stok itu',
    param: { key: 'percent', label: 'Persen', def: '20', step: '1', suffix: '%' },
  },
  {
    key: 'fixed',
    label: 'Angka yang saya tentukan',
    hint: 'satu angka untuk seluruh seleksi — cocok per jenis / per kategori',
    param: null,
  },
];
const labelDasar = (k) => (MODES.find((m) => m.key === k) || {}).label || 'Dasar lain';

/**
 * Ambang Stok — layar tempat pemilik MENGISI ambang minimum & titik pesan ulang.
 *
 * Sesi #29 (W3) membuat layar ini karena alert stok tidak pernah berbunyi: 333
 * dari 333 material tidak punya ambang. Sesi #33 menutup lubang yang tersisa:
 * usulan lama HANYA lahir dari pemakaian 30 hari, dan terukur di data nyata
 * hanya **5 dari 335 material** yang punya pemakaian ⇒ tombol "Pakai semua
 * usulan" secara struktural cuma bisa mengisi 5 baris, 330 sisanya harus
 * diketik satu per satu. Sekarang ada EMPAT dasar pengisian massal, semuanya
 * bisa dipratinjau lebih dulu, bisa dikosongkan lagi, dan DASARNYA disimpan
 * bersama siapa & kapan supaya tidak ada angka anonim.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout; panel "Isi ambang massal" (form) → FormPopup panjang; kartu
 * angka → StatTile; status → StatusBadge; unduh Excel/CSV; konfirmasi kosongkan → confirmDialog.
 * Perbaikan data: daftar dulu memakai limit=1000 padahal ada 1.726 barang aktif — 726 barang tidak pernah
 * tampil dan label "semua hasil filter (1000 baris)" keliru. Kini limit 5000 + halaman 50 baris di layar.
 */
export default function StockThresholdsModule({ token, onNavigate }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [edits, setEdits] = useState({});           // material_id -> {min_stock_qty, reorder_point}
  const [filterType, setFilterType] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [search, setSearch] = useState('');
  const [cari, setCari] = useState('');
  const [selected, setSelected] = useState(() => new Set());
  const [bulkOpen, setBulkOpen] = useState(false);
  const [mode, setMode] = useState('purchase_lot');
  const [params, setParams] = useState({ lot_multiplier: '0.5', percent: '20',
    min_stock_qty: '', reorder_point: '' });
  const [preview, setPreview] = useState(null);
  const [busyBulk, setBusyBulk] = useState(false);

  const headers = useMemo(() => ({
    Authorization: `Bearer ${token || localStorage.getItem('erp_token')}`,
    'Content-Type': 'application/json',
  }), [token]);

  const goto = useCallback((moduleId) => {
    if (onNavigate) { onNavigate(moduleId); return; }
    if (window.location.hash === `#${moduleId}`) window.location.hash = '';
    window.location.hash = `#${moduleId}`;
  }, [onNavigate]);

  useEffect(() => {
    const t = setTimeout(() => setSearch(cari), 300);
    return () => clearTimeout(t);
  }, [cari]);

  const fetchRows = useCallback(async () => {
    setLoading(true);
    try {
      // 1.726 barang aktif di data nyata — limit 1000 dulu memotong 726 barang tanpa tanda.
      const p = new URLSearchParams({ status: filterStatus, limit: 5000 });
      if (filterType) p.set('type', filterType);
      if (search.trim()) p.set('search', search.trim());
      const r = await fetch(`/api/rahaza/stock-thresholds?${p}`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setRows(d.items || []);
      setSummary(d.summary || null);
      setEdits({});
      setSelected(new Set());
    } catch (e) {
      toast.error(`Gagal memuat ambang stok: ${e.message}`);
    } finally { setLoading(false); }
  }, [headers, filterType, filterStatus, search]);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  const setEdit = (id, field, value) => setEdits(prev => ({
    ...prev, [id]: { ...(prev[id] || {}), [field]: value },
  }));

  const valueOf = (r, field) => {
    const e = edits[r.material_id];
    if (e && e[field] !== undefined) return e[field];
    return r[field] ? String(r[field]) : '';
  };

  const applySuggestion = (r) => {
    const s = r.suggestion || {};
    if (s.no_usage_data) {
      toast.error(`${r.code} belum ada pemakaian 30 hari terakhir — pakai dasar "Dari lot pembelian" pada Isi ambang massal.`);
      return;
    }
    setEdits(prev => ({
      ...prev,
      [r.material_id]: {
        min_stock_qty: String(s.suggested_min_stock),
        reorder_point: String(s.suggested_reorder_point),
      },
    }));
  };

  const applyAllSuggestions = () => {
    const next = { ...edits };
    let n = 0;
    let skipped = 0;
    rows.forEach(r => {
      const s = r.suggestion || {};
      if (s.no_usage_data || !s.suggested_min_stock) { skipped += 1; return; }
      next[r.material_id] = {
        min_stock_qty: String(s.suggested_min_stock),
        reorder_point: String(s.suggested_reorder_point),
      };
      n += 1;
    });
    setEdits(next);
    if (n) {
      toast.success(`${n} usulan disiapkan — klik Simpan untuk menerapkan.`
        + (skipped ? ` ${skipped} barang tidak punya pemakaian 30 hari; pakai Isi ambang massal (dasar "Dari lot pembelian") untuk barang-barang itu.` : ''));
    } else {
      toast.error(`Tidak ada barang dengan pemakaian nyata di daftar ini (${skipped} barang dilewati) — `
        + 'pakai Isi ambang massal dengan dasar "Dari lot pembelian" atau "Persen stok sekarang".');
    }
  };

  const dirtyItems = useMemo(() => Object.entries(edits).map(([material_id, v]) => ({
    material_id,
    min_stock_qty: num(v.min_stock_qty),
    reorder_point: num(v.reorder_point),
  })).filter(it => {
    const r = rows.find(x => x.material_id === it.material_id);
    if (!r) return false;
    return num(r.min_stock_qty) !== it.min_stock_qty || num(r.reorder_point) !== it.reorder_point;
  }), [edits, rows]);

  const save = async () => {
    if (!dirtyItems.length) return;
    setSaving(true);
    try {
      const r = await fetch('/api/rahaza/stock-thresholds/bulk', {
        method: 'POST', headers, body: JSON.stringify({ items: dirtyItems }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      toast.success(`${d.updated} ambang stok disimpan — alert langsung aktif.`);
      fetchRows();
    } catch (e) {
      toast.error(`Gagal menyimpan: ${e.message}`);
    } finally { setSaving(false); }
  };

  // ── ISI MASSAL ────────────────────────────────────────────────────────────
  const scope = useMemo(() => {
    if (selected.size) return { material_ids: Array.from(selected) };
    return {
      type: filterType || undefined,
      search: search.trim() || undefined,
      status: filterStatus !== 'all' ? filterStatus : undefined,
    };
  }, [selected, filterType, search, filterStatus]);

  const scopeLabel = selected.size
    ? `${angka(selected.size)} baris tercentang`
    : `semua hasil saringan (${angka(rows.length)} baris)`;

  const activeMode = MODES.find(m => m.key === mode) || MODES[0];

  const bulkBody = useCallback((dry) => {
    const p = {};
    if (mode === 'percent_onhand') p.percent = num(params.percent);
    if (mode === 'purchase_lot') p.lot_multiplier = num(params.lot_multiplier);
    if (mode === 'fixed') {
      p.min_stock_qty = num(params.min_stock_qty);
      p.reorder_point = num(params.reorder_point);
    }
    return { mode, dry_run: dry, params: p, scope };
  }, [mode, params, scope]);

  const runBulk = async (dry) => {
    if (mode === 'fixed' && num(params.min_stock_qty) <= 0 && num(params.reorder_point) <= 0) {
      toast.error('Isi minimal salah satu: minimum stok atau titik pesan ulang.');
      return;
    }
    setBusyBulk(true);
    try {
      const r = await fetch('/api/rahaza/stock-thresholds/bulk-fill', {
        method: 'POST', headers, body: JSON.stringify(bulkBody(dry)),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setPreview(d);
      if (dry) {
        toast.success(d.eligible
          ? `Pratinjau: ${d.eligible} barang akan diisi (${d.skipped_count} dilewati). Belum ada yang ditulis.`
          : `Tidak ada barang yang bisa diisi dengan dasar ini — ${d.skipped_count} dilewati beserta alasannya.`);
      } else {
        toast.success(`${d.applied} ambang terisi dengan dasar "${d.basis_label}" — alert langsung aktif.`);
        fetchRows();
      }
    } catch (e) {
      toast.error(`Gagal: ${e.message}`);
    } finally { setBusyBulk(false); }
  };

  const clearSelected = async () => {
    if (!selected.size) {
      toast.error('Centang dulu baris yang ambangnya mau dikosongkan.');
      return;
    }
    const ok = await confirmDialog({
      title: `Kosongkan ambang ${selected.size} barang?`,
      body: 'Peringatan stok untuk barang itu akan berhenti berbunyi.',
      confirmLabel: 'Kosongkan', danger: true,
    });
    if (!ok) return;
    setBusyBulk(true);
    try {
      const r = await fetch('/api/rahaza/stock-thresholds/bulk-clear', {
        method: 'POST', headers, body: JSON.stringify({ material_ids: Array.from(selected) }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      toast.success(`${d.cleared} ambang dikosongkan.`);
      setPreview(null);
      fetchRows();
    } catch (e) {
      toast.error(`Gagal mengosongkan: ${e.message}`);
    } finally { setBusyBulk(false); }
  };

  const toggle = (id) => setSelected(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const toggleAll = () => setSelected(prev =>
    prev.size === rows.length ? new Set() : new Set(rows.map(r => r.material_id)));

  const pg = useClientPagination(rows, 50);
  const semuaTercentang = rows.length > 0 && selected.size === rows.length;

  return (
    <PageLayout testId="stock-thresholds-page" title="Ambang stok"
      subtitle="Minimum stok dan titik pesan ulang; alert dan Belanja Mingguan hanya bekerja untuk barang berambang."
      actions={<>
        <Button variant="outline" onClick={() => setBulkOpen(true)} data-testid="threshold-bulk-toggle">
          <Layers />Isi ambang massal
        </Button>
        <Button variant="outline" onClick={applyAllSuggestions} data-testid="threshold-apply-all">
          <Wand2 />Pakai semua usulan
        </Button>
        <Button variant="success" onClick={save} disabled={saving || !dirtyItems.length} data-testid="threshold-save">
          <Save />{saving ? 'Menyimpan…' : `Simpan${dirtyItems.length ? ` (${dirtyItems.length})` : ''}`}
        </Button>
      </>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={e => setCari(e.target.value)} placeholder="Cari kode atau nama"
            className="pl-8" data-testid="threshold-search" />
        </div>
        <SmartNativeSelect value={filterType} onChange={e => setFilterType(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-40"
          searchable={false} aria-label="Jenis" data-testid="threshold-filter-type">
          <option value="">Semua jenis</option>
          <option value="bahan">Bahan</option>
          <option value="aksesoris">Aksesoris</option>
          <option value="fg">Produk jadi</option>
        </SmartNativeSelect>
        <SmartNativeSelect value={filterStatus} onChange={e => setFilterStatus(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-52"
          searchable={false} aria-label="Status ambang" data-testid="threshold-filter-status">
          <option value="all">Semua status</option>
          <option value="missing">Belum ada ambang</option>
          <option value="set">Sudah ada ambang</option>
          <option value="low">Sedang rendah / kritis</option>
        </SmartNativeSelect>
        <div className="ml-auto flex shrink-0 items-center gap-2">
        <Button variant="link" onClick={() => goto('wh-shopping-list')} data-testid="threshold-goto-shopping">
          <ShoppingCart />Belanja mingguan
        </Button>
        <TombolUnduh namaBerkas="ambang-stok" namaLembar="Ambang stok" baris={rows} testId="threshold-unduh"
          kolom={[
            { label: 'Kode', nilai: (r) => r.code },
            { label: 'Nama', nilai: (r) => r.name },
            { label: 'Jenis', nilai: (r) => jenisLabel(r.type) },
            { label: 'Satuan', nilai: (r) => r.unit },
            { label: 'Stok', nilai: (r) => Number(r.onhand || 0) },
            { label: 'Min stok', nilai: (r) => Number(r.min_stock_qty || 0) },
            { label: 'Titik pesan ulang', nilai: (r) => Number(r.reorder_point || 0) },
            { label: 'Dasar', nilai: (r) => (r.threshold_basis ? labelDasar(r.threshold_basis) : '') },
            { label: 'Keterangan dasar', nilai: (r) => r.threshold_basis_note || '' },
            { label: 'Diisi oleh', nilai: (r) => r.threshold_set_by || '' },
            { label: 'Tanggal diisi', nilai: (r) => (r.threshold_set_at ? formatDateID(r.threshold_set_at) : '') },
            { label: 'Status', nilai: (r) => (STATUS_META[r.status] || STATUS_META.no_threshold).label },
            { label: 'Kekurangan', nilai: (r) => Number(r.shortage || 0) },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchRows} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="threshold-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
        </div>
      </>}
      summary={summary ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="threshold-summary">
            <StatTile label="Sudah punya ambang" value={angka(summary.with_threshold)} testId="threshold-stat-with_threshold"
              sub={`dari ${angka(summary.total_materials)} barang aktif`} />
            <StatTile label="Belum diisi" value={angka(summary.missing_threshold)} testId="threshold-stat-missing_threshold"
              accent={summary.missing_threshold ? 'warning' : 'default'} sub="belum bisa dinilai perlu dibeli atau tidak" />
            <StatTile label="Stok kritis" value={angka(summary.critical)} testId="threshold-stat-critical"
              accent={summary.critical ? 'danger' : 'default'} sub="stok di bawah minimum" />
            <StatTile label="Perlu pesan ulang" value={angka(summary.low)} testId="threshold-stat-low"
              accent={summary.low ? 'warning' : 'default'} sub="di bawah titik pesan ulang, belum kritis" />
          </div>
          {summary.with_threshold === 0 && (
            <Notice tone="warning" icon={AlertTriangle} testId="threshold-empty-warning"
              title="Belum ada satu pun ambang stok yang diisi">
              Itulah sebabnya Alert &amp; Reorder dan Belanja Mingguan kosong. Pakai Isi ambang massal: mulai dari
              lot pembelian (paling banyak barang yang tercakup), lalu sesuaikan yang perlu.
            </Notice>
          )}
        </div>
      ) : null}
      footer={pg.total > pg.pageSize ? (
        <PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total} pageSize={pg.pageSize} onPageChange={pg.setPage} />
      ) : null}>
      {loading && rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat ambang stok…</p>
      ) : rows.length === 0 ? (
        <EmptyState title="Tidak ada barang pada saringan ini" description="Ubah jenis, status, atau kata pencarian." />
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Isi minimum dan titik pesan ulang langsung di tabel, lalu klik Simpan. Centang baris untuk membatasi Isi ambang
            massal atau mengosongkan ambang.{selected.size ? ` ${angka(selected.size)} baris tercentang.` : ''}
          </p>
          <div className="overflow-x-auto">
            <Table data-testid="threshold-table">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <Checkbox checked={semuaTercentang} onCheckedChange={toggleAll} aria-label="Centang semua baris"
                      data-testid="threshold-select-all" />
                  </TableHead>
                  <TableHead>Barang</TableHead>
                  <TableHead className="text-right">Stok</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Min stok</TableHead>
                  <TableHead className="text-right">Titik pesan ulang</TableHead>
                  <TableHead>Usulan (pemakaian nyata)</TableHead>
                  <TableHead>Dasar</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pg.paged.map(r => {
                  const s = r.suggestion || {};
                  const meta = STATUS_META[r.status] || STATUS_META.no_threshold;
                  const dirty = !!edits[r.material_id];
                  const isSel = selected.has(r.material_id);
                  return (
                    <TableRow key={r.material_id} className={dirty || isSel ? 'bg-primary/5' : undefined}
                      data-testid={`threshold-row-${r.code}`}>
                      <TableCell>
                        <Checkbox checked={isSel} onCheckedChange={() => toggle(r.material_id)} aria-label={`Centang ${r.code}`}
                          data-testid={`threshold-check-${r.code}`} />
                      </TableCell>
                      <TableCell className="min-w-[12rem]">
                        <div className="tabular-nums text-xs text-muted-foreground">{r.code}</div>
                        <div className="text-foreground">{r.name}</div>
                        <div className="text-xs text-muted-foreground">{jenisLabel(r.type)} · {r.unit}</div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap">
                        {fmt(r.onhand)} {r.unit}
                      </TableCell>
                      <TableCell>
                        <span data-testid={`threshold-status-${r.code}`}>
                          <StatusBadge status={r.status} label={meta.label} tone={meta.tone} />
                        </span>
                        {r.shortage > 0 && (
                          <span className="mt-0.5 block text-xs text-muted-foreground">kurang {fmt(r.shortage)} {r.unit}</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <Input type="number" step="0.01" min="0" value={valueOf(r, 'min_stock_qty')}
                          onChange={e => setEdit(r.material_id, 'min_stock_qty', e.target.value)}
                          placeholder="0" className="ml-auto h-8 w-24 text-right" aria-label={`Min stok ${r.code}`}
                          data-testid={`threshold-min-${r.code}`} />
                      </TableCell>
                      <TableCell className="text-right">
                        <Input type="number" step="0.01" min="0" value={valueOf(r, 'reorder_point')}
                          onChange={e => setEdit(r.material_id, 'reorder_point', e.target.value)}
                          placeholder="0" className="ml-auto h-8 w-24 text-right" aria-label={`Titik pesan ulang ${r.code}`}
                          data-testid={`threshold-rp-${r.code}`} />
                      </TableCell>
                      <TableCell className="min-w-[12rem] text-xs">
                        {s.no_usage_data ? (
                          <span className="inline-flex items-center gap-1 text-muted-foreground">
                            <Info className="h-3 w-3" /> belum ada pemakaian 30 hari
                          </span>
                        ) : (
                          <div>
                            <Button variant="link" size="sm" className="h-auto p-0" onClick={() => applySuggestion(r)}
                              data-testid={`threshold-use-suggestion-${r.code}`}>
                              Pakai: min {s.suggested_min_stock} · pesan ulang {s.suggested_reorder_point}
                            </Button>
                            <span className="block text-muted-foreground">
                              {s.avg_daily_consumption}/hari × {s.lead_time_days} hari · {s.movements_30d} transaksi
                            </span>
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="min-w-[10rem] text-xs" data-testid={`threshold-basis-${r.code}`}>
                        {r.threshold_basis ? (
                          <>
                            <StatusBadge status="dasar" label={labelDasar(r.threshold_basis)} tone="default" />
                            {r.threshold_basis_note && (
                              <span className="mt-0.5 block line-clamp-2 text-muted-foreground" title={r.threshold_basis_note}>
                                {r.threshold_basis_note}
                              </span>
                            )}
                            {r.threshold_set_by && (
                              <span className="block text-muted-foreground">
                                oleh {r.threshold_set_by} · {formatDateID(r.threshold_set_at)}
                              </span>
                            )}
                          </>
                        ) : (
                          <span className="text-muted-foreground">
                            {r.has_threshold ? 'diisi sebelum jejak dasar dicatat' : 'belum diisi'}
                          </span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {/* ── ISI AMBANG MASSAL (form → popup) ─────────────────────────────────── */}
      <FormPopup open={bulkOpen} onClose={() => { setBulkOpen(false); setPreview(null); }} ukuran="panjang"
        judul="Isi ambang massal" testId="threshold-bulk-panel"
        keterangan={`Berlaku untuk ${scopeLabel}. Tanpa centang, penerapan mengikuti saringan di halaman. Pratinjau tidak menulis apa pun.`}
        onSimpan={() => runBulk(false)} menyimpan={busyBulk} labelSimpan="Terapkan"
        aksiKiri={<>
          <Button type="button" variant="outline" onClick={clearSelected} disabled={busyBulk || !selected.size}
            data-testid="threshold-bulk-clear"><Eraser />Kosongkan terpilih</Button>
          <Button type="button" variant="outline" onClick={() => runBulk(true)} disabled={busyBulk}
            data-testid="threshold-bulk-preview"><Wand2 />Pratinjau</Button>
        </>}>
        <Isian label="Dasar pengisian">
          <RadioGroup value={mode} onValueChange={(v) => { setMode(v); setPreview(null); }} className="gap-3">
            {MODES.map(m => (
              <label key={m.key} htmlFor={`threshold-mode-${m.key}`} className="flex cursor-pointer items-start gap-2"
                data-testid={`threshold-mode-${m.key}`}>
                <RadioGroupItem id={`threshold-mode-${m.key}`} value={m.key} className="mt-0.5" />
                <span>
                  <span className="block text-sm font-medium text-foreground">{m.label}</span>
                  <span className="block text-xs text-muted-foreground">{m.hint}</span>
                </span>
              </label>
            ))}
          </RadioGroup>
        </Isian>

        {(activeMode.param || mode === 'fixed') && (
          <div className="grid gap-4 sm:grid-cols-3">
            {activeMode.param && (
              <Isian label={`${activeMode.param.label} (${activeMode.param.suffix})`} htmlFor="threshold-param">
                <Input id="threshold-param" type="number" step={activeMode.param.step} min="0"
                  value={params[activeMode.param.key]}
                  onChange={e => setParams(p => ({ ...p, [activeMode.param.key]: e.target.value }))}
                  data-testid={`threshold-param-${activeMode.param.key}`} />
              </Isian>
            )}
            {mode === 'fixed' && (
              <>
                <Isian label="Minimum stok" htmlFor="threshold-param-min">
                  <Input id="threshold-param-min" type="number" step="0.01" min="0" value={params.min_stock_qty}
                    onChange={e => setParams(p => ({ ...p, min_stock_qty: e.target.value }))}
                    placeholder="0" data-testid="threshold-param-min" />
                </Isian>
                <Isian label="Titik pesan ulang" htmlFor="threshold-param-rp">
                  <Input id="threshold-param-rp" type="number" step="0.01" min="0" value={params.reorder_point}
                    onChange={e => setParams(p => ({ ...p, reorder_point: e.target.value }))}
                    placeholder="0" data-testid="threshold-param-rp" />
                </Isian>
              </>
            )}
          </div>
        )}

        {preview && (
          <div className="space-y-2" data-testid="threshold-preview">
            <p className="text-sm">
              <span className="font-medium text-foreground">
                {preview.dry_run ? 'Pratinjau' : 'Diterapkan'} · dasar {preview.basis_label}
              </span>
              <span className="text-muted-foreground"> · diperiksa {preview.scanned} barang · </span>
              <span className="text-[hsl(var(--success-text))]" data-testid="threshold-preview-eligible">
                {preview.dry_run ? `${preview.eligible} akan diisi` : `${preview.applied} terisi`}
              </span>
              {preview.skipped_count > 0 && (
                <span className="text-[hsl(var(--warning-text))]" data-testid="threshold-preview-skipped">
                  {' '}· {preview.skipped_count} dilewati
                </span>
              )}
            </p>
            {!!(preview.preview || []).length && (
              <div className="max-h-56 overflow-auto rounded-md border border-[var(--glass-border)]">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Kode</TableHead>
                      <TableHead className="text-right">Stok</TableHead>
                      <TableHead className="text-right">Min sekarang</TableHead>
                      <TableHead className="text-right">Min baru</TableHead>
                      <TableHead className="text-right">Pesan ulang baru</TableHead>
                      <TableHead>Dasar angkanya</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {preview.preview.slice(0, 30).map(p => (
                      <TableRow key={p.material_id} data-testid={`threshold-preview-row-${p.code}`}>
                        <TableCell className="tabular-nums">{p.code}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmt(p.onhand)} {p.unit}</TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">{fmt(p.current_min)}</TableCell>
                        <TableCell className="text-right tabular-nums font-medium">{fmt(p.min_stock_qty)}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmt(p.reorder_point)}</TableCell>
                        <TableCell className="text-muted-foreground">{p.basis_note}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            {(preview.preview || []).length > 30 && (
              <p className="text-xs text-muted-foreground">
                …dan {preview.preview.length - 30} baris lain (semua akan ikut diterapkan)
              </p>
            )}
            {!!(preview.skipped || []).length && (
              <p className="text-xs text-muted-foreground">
                <span className="font-medium text-[hsl(var(--warning-text))]">Dilewati:</span>{' '}
                {preview.skipped.slice(0, 4).map(s => `${s.code} (${s.reason})`).join(' · ')}
                {preview.skipped.length > 4 && ` · dan ${preview.skipped.length - 4} lainnya`}
              </p>
            )}
          </div>
        )}
      </FormPopup>
    </PageLayout>
  );
}

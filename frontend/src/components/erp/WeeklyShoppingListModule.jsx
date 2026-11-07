import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  RefreshCw, AlertTriangle, CheckCircle2, FileText, Info, Search,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import FilterChips from '@/components/ui/filter-chips';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

/**
 * Daftar Belanja Mingguan (sesi #33) — "minggu ini saya harus belanja apa?"
 *
 * Kenapa layar ini ada: sebelum sesi #33 tidak ada satu pun layar yang menjawab
 * pertanyaan itu. `Alert & Reorder` hanya bilang "kurang n" tanpa satuan beli,
 * tanpa harga, dan tanpa jembatan ke Permintaan Pengadaan ⇒ hasilnya harus
 * diketik ulang manual. Kebutuhan di sini dihitung HANYA dari ambang minimum /
 * titik pesan ulang (keputusan pemilik), stok dibaca kanonik, qty dibulatkan ke
 * atas ke satuan BELI, dan MOQ supplier nyata menaikkan qty dengan alasan yang
 * disebut. Barang tanpa harga TIDAK diam-diam dihitung Rp0.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, tab Radix (dulu garis bawah buatan), StatTile berketerangan,
 * penyaring satu baris, unduh Excel/CSV, form "Buat PR" = FormPopup panjang dengan DatePicker.
 * Kode mentah (min_stock, accessory, draft) diganti label. Semua angka kartu = `summary` API yang sama dengan
 * daftar (ikut saringan jenis/cari) — diverifikasi 8 Nov 2026: 43 baris, Rp 9.803.558 = Σ est_total baris berharga.
 */

const rp = (v) => `Rp${Math.round(Number(v) || 0).toLocaleString('id-ID')}`;
const num = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 });

const STATUS_META = {
  critical: { label: 'Kritis', tone: 'danger' },
  low: { label: 'Perlu pesan', tone: 'warning' },
};
const JENIS_LABEL = {
  yarn: 'Bahan', fabric: 'Bahan', kain: 'Bahan', benang: 'Bahan', interlining: 'Bahan',
  accessory: 'Aksesoris', packaging: 'Aksesoris', fg: 'Produk jadi',
};
const jenisLabel = (t) => JENIS_LABEL[t] || 'Lainnya';
const DASAR_LABEL = {
  purchase_lot: 'dari lot pembelian', usage_30d: 'dari pemakaian 30 hari',
  percent_onhand: 'persen stok sekarang', fixed: 'angka ditentukan',
};
const SUMBER_AMBANG = {
  min_stock_qty: 'min stok', min_stock: 'min stok (lama)', min_stock_percentage: 'persen stok tertinggi',
  reorder_point: 'titik pesan ulang',
};
const keteranganAmbang = (r) => (r.threshold_basis
  ? `dasar: ${DASAR_LABEL[r.threshold_basis] || 'lainnya'}`
  : (SUMBER_AMBANG[r.threshold_source] || ''));
const STATUS_PR = {
  draft: { label: 'Draf', tone: 'muted' },
  submitted: { label: 'Menunggu persetujuan dept', tone: 'warning' },
  dept_approved: { label: 'Menunggu persetujuan keuangan', tone: 'warning' },
  finance_approved: { label: 'Menunggu persetujuan final', tone: 'warning' },
  approved: { label: 'Disetujui', tone: 'success' },
  in_procurement: { label: 'Sedang pengadaan', tone: 'info' },
  rejected: { label: 'Ditolak', tone: 'danger' },
  completed: { label: 'Selesai', tone: 'success' },
  cancelled: { label: 'Dibatalkan', tone: 'muted' },
};
const statusPr = (s) => STATUS_PR[s] || { label: s ? 'Lainnya' : '—', tone: 'muted' };

export default function WeeklyShoppingListModule({ token, onNavigate }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [week, setWeek] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('list');
  const [history, setHistory] = useState(null);
  const [search, setSearch] = useState('');
  const [cari, setCari] = useState('');
  const [filterType, setFilterType] = useState('');
  const [hideRequested, setHideRequested] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const [dialogOpen, setDialogOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [notes, setNotes] = useState('');
  const [neededBy, setNeededBy] = useState('');
  const [lastPR, setLastPR] = useState(null);

  const headers = useMemo(() => ({
    Authorization: `Bearer ${token || localStorage.getItem('erp_token')}`,
    'Content-Type': 'application/json',
  }), [token]);

  const goto = useCallback((moduleId, tabKey) => {
    if (tabKey) { try { sessionStorage.setItem(`hub_tab_${moduleId}`, tabKey); } catch (e) { /* noop */ } }
    if (onNavigate) { onNavigate(moduleId); return; }
    const target = tabKey ? `#${moduleId}=${tabKey}` : `#${moduleId}`;
    if (window.location.hash === target) window.location.hash = '';
    window.location.hash = target;
  }, [onNavigate]);

  useEffect(() => {
    const t = setTimeout(() => setSearch(cari), 300);
    return () => clearTimeout(t);
  }, [cari]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({ include_requested: String(!hideRequested) });
      if (filterType) p.set('type', filterType);
      if (search.trim()) p.set('search', search.trim());
      const r = await fetch(`/api/rahaza/shopping-list/weekly?${p}`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setRows(d.rows || []);
      setSummary(d.summary || null);
      setWeek(d.week || null);
      setSelected(new Set());
    } catch (e) {
      toast.error(`Gagal memuat daftar belanja: ${e.message}`);
    } finally { setLoading(false); }
  }, [headers, filterType, search, hideRequested]);

  const loadHistory = useCallback(async () => {
    try {
      const r = await fetch('/api/rahaza/shopping-list/history?limit=100', { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setHistory(await r.json());
    } catch (e) {
      toast.error(`Gagal memuat riwayat: ${e.message}`);
    }
  }, [headers]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (tab === 'history' && !history) loadHistory(); }, [tab, history, loadHistory]);

  const selectable = useMemo(() => rows.filter(r => !r.already_requested), [rows]);
  const chosen = useMemo(() => rows.filter(r => selected.has(r.material_id)), [rows, selected]);
  const chosenTotal = useMemo(
    () => chosen.reduce((s, r) => s + (r.valued ? Number(r.est_total || 0) : 0), 0), [chosen]);

  const toggle = (id) => setSelected(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const toggleAll = () => setSelected(prev =>
    prev.size === selectable.length ? new Set() : new Set(selectable.map(r => r.material_id)));

  const createPR = async () => {
    if (!chosen.length) return;
    setCreating(true);
    try {
      const r = await fetch('/api/rahaza/shopping-list/create-pr', {
        method: 'POST', headers,
        body: JSON.stringify({
          material_ids: chosen.map(c => c.material_id),
          notes: notes.trim() || undefined,
          needed_by: neededBy || undefined,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setLastPR({ ...(d.request || {}), skipped: d.skipped || [] });
      setDialogOpen(false);
      setNotes(''); setNeededBy('');
      toast.success(d.pesan || `Permintaan Pengadaan ${d.request?.request_number} dibuat.`);
      setHistory(null);
      load();
    } catch (e) {
      toast.error(`Gagal membuat PR: ${e.message}`);
    } finally { setCreating(false); }
  };

  const muatUlang = () => { if (tab === 'history') { setHistory(null); loadHistory(); } else load(); };
  const semuaTercentang = selectable.length > 0 && selected.size === selectable.length;

  const kolomRiwayat = [
    { kunci: 'number', label: 'Nomor PR', hp: 'judul', isi: (h) => <span className="tabular-nums" data-testid={`shopping-history-row-${h.number}`}>{h.number}</span> },
    { kunci: 'hp-ket', label: '', hp: 'keterangan', lebar: 'hidden', isi: (h) => `Minggu ${h.week} · ${h.lines} baris` },
    { kunci: 'week', label: 'Minggu', hp: false, isi: (h) => h.week },
    { kunci: 'status', label: 'Status', isi: (h) => { const s = statusPr(h.status); return <StatusBadge status={h.status} label={s.label} tone={s.tone} />; } },
    { kunci: 'lines', label: 'Baris', hp: false, rata: 'kanan', isi: (h) => <span className="tabular-nums">{h.lines}</span> },
    { kunci: 'total', label: 'Perkiraan nilai', rata: 'kanan', isi: (h) => <span className="tabular-nums">{rp(h.total_estimated)}</span> },
    { kunci: 'by', label: 'Diminta oleh', hp: false, isi: (h) => h.requested_by_name || '—' },
    { kunci: 'barang', label: 'Barang', hp: false, isi: (h) => (
      <span className="line-clamp-2 text-xs text-muted-foreground">
        {(h.materials || []).map(m => `${m.code || ''} ${num(m.qty)} ${m.uom}`).join(' · ')}
      </span>) },
  ];

  return (
      <PageLayout testId="shopping-list-page" title="Belanja mingguan"
        subtitle="Barang yang perlu dibeli minggu ini, dihitung dari ambang minimum / titik pesan ulang dan stok semua lokasi."
        actions={
          <Button onClick={() => setDialogOpen(true)} disabled={!chosen.length} data-testid="shopping-create-pr">
            <FileText />Buat PR pengadaan{chosen.length ? ` (${chosen.length})` : ''}
          </Button>
        }
        filters={<>
          <FilterChips value={tab} onChange={setTab} hideWhenEmpty={false} testId="shopping-tab" ariaLabel="Tampilan" className="w-full sm:w-auto"
            options={[{ key: 'list', label: 'Perlu dibeli' }, { key: 'history', label: 'PR dari layar ini' }]} />
          {tab === 'list' && <>
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={cari} onChange={e => setCari(e.target.value)} placeholder="Cari kode atau nama"
                className="pl-8" data-testid="shopping-search" />
            </div>
            <SmartNativeSelect value={filterType} onChange={e => setFilterType(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-48"
              searchable={false} aria-label="Jenis" data-testid="shopping-filter-type">
              <option value="">Semua jenis</option>
              <option value="bahan">Bahan (kain/benang)</option>
              <option value="aksesoris">Aksesoris</option>
              <option value="fg">Produk jadi</option>
            </SmartNativeSelect>
            <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-foreground">
              <Checkbox checked={hideRequested} onCheckedChange={(v) => setHideRequested(!!v)} data-testid="shopping-hide-requested" />
              Sembunyikan yang sudah ber-PR
            </label>
          </>}
          <div className="ml-auto flex shrink-0 items-center gap-2">
          {tab === 'list' ? (
            <TombolUnduh namaBerkas={`belanja-mingguan${week?.iso ? `-${week.iso}` : ''}`} namaLembar="Belanja mingguan" baris={rows}
              testId="shopping-unduh"
              kolom={[
                { label: 'Kode', nilai: (r) => r.code },
                { label: 'Nama', nilai: (r) => r.name },
                { label: 'Jenis', nilai: (r) => jenisLabel(r.type) },
                { label: 'Satuan dasar', nilai: (r) => r.base_uom },
                { label: 'Stok', nilai: (r) => Number(r.onhand || 0) },
                { label: 'Ambang', nilai: (r) => Number(r.alert_at || 0) },
                { label: 'Kurang', nilai: (r) => Number(r.shortage || 0) },
                { label: 'Sisa PO terbuka', nilai: (r) => Number(r.incoming_po_qty || 0) },
                { label: 'Qty beli', nilai: (r) => Number(r.qty_buy || 0) },
                { label: 'Satuan beli', nilai: (r) => r.purchase_uom },
                { label: 'Harga per satuan beli (Rp)', nilai: (r) => (r.valued ? Number(r.price_per_purchase_uom || 0) : '') },
                { label: 'Perkiraan total (Rp)', nilai: (r) => (r.valued ? Number(r.est_total || 0) : '') },
                { label: 'Supplier', nilai: (r) => r.supplier?.name || '' },
                { label: 'Status', nilai: (r) => (r.already_requested ? `Sudah ber-PR ${(r.pr || {}).number || ''}`.trim() : (STATUS_META[r.stock_status] || STATUS_META.low).label) },
              ]} />
          ) : (
            <TombolUnduh namaBerkas="pr-dari-belanja-mingguan" namaLembar="PR" baris={history?.items || []} testId="shopping-history-unduh"
              kolom={[
                { label: 'Nomor PR', nilai: (h) => h.number },
                { label: 'Minggu', nilai: (h) => h.week },
                { label: 'Status', nilai: (h) => statusPr(h.status).label },
                { label: 'Baris', nilai: (h) => Number(h.lines || 0) },
                { label: 'Perkiraan nilai (Rp)', nilai: (h) => Number(h.total_estimated || 0) },
                { label: 'Diminta oleh', nilai: (h) => h.requested_by_name || '' },
                { label: 'Barang', nilai: (h) => (h.materials || []).map(m => `${m.code || ''} ${num(m.qty)} ${m.uom}`).join(' · ') },
              ]} />
          )}
          <Button variant="outline" size="icon" onClick={muatUlang} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
            data-testid="shopping-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
          </div>
        </>}
        summary={tab === 'list' && summary ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="shopping-summary">
              <StatTile label="Perlu dibeli minggu ini" value={num(summary.need_buy)} testId="shopping-stat-need_buy"
                sub={`${num(summary.critical || 0)} kritis · ${num(summary.with_supplier || 0)} punya supplier`} />
              <StatTile label="Perkiraan nilai belanja" value={rp(summary.est_total_value)} testId="shopping-stat-value"
                sub="harga supplier / HPP pembelian" />
              <StatTile label="Belum berharga" value={num(summary.unvalued_count)} testId="shopping-stat-unvalued"
                accent={summary.unvalued_count ? 'warning' : 'default'} sub="tidak masuk perkiraan nilai" />
              <StatTile label="Belum berambang" value={num(summary.without_threshold)} testId="shopping-stat-no_threshold"
                accent={summary.without_threshold ? 'warning' : 'default'} sub={`dari ${num(summary.total_materials)} barang aktif`} />
            </div>
            <p className="text-xs text-muted-foreground" data-testid="shopping-week-label">
              {week ? `Minggu ${week.week} · ${week.label}` : 'Menghitung minggu…'}
            </p>
            {summary.without_threshold > 0 && (
              <Notice tone="warning" icon={AlertTriangle} testId="shopping-threshold-notice">
                <p>{String(summary.without_threshold_note || '').replace(/\bBELUM\b/g, 'belum')}</p>
                <Button variant="outline" size="sm" className="mt-2" onClick={() => goto('wh-master', 'thresholds')}
                  data-testid="shopping-goto-thresholds">Isi ambang massal</Button>
              </Notice>
            )}
            {lastPR && (
              <Notice tone="success" icon={CheckCircle2} testId="shopping-pr-result"
                title={`${lastPR.request_number} dibuat sebagai draf · ${(lastPR.items || []).length} barang · ${rp(lastPR.total_estimated)}`}>
                {!!(lastPR.skipped || []).length && (
                  <p className="text-xs">
                    {lastPR.skipped.length} barang dilewati: {lastPR.skipped.map(s => `${s.code || s.material_id} (${s.reason})`).join('; ')}
                  </p>
                )}
                <Button variant="outline" size="sm" className="mt-2" onClick={() => goto('proc-requests')} data-testid="shopping-open-pr">
                  Buka Permintaan Pengadaan</Button>
              </Notice>
            )}
          </div>
        ) : null}>

        {tab === 'list' && (<div className="space-y-3">
          {loading && rows.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Memuat daftar belanja…</p>
          ) : rows.length === 0 ? (
            <div data-testid="shopping-empty">
              {summary && summary.with_threshold === 0 ? (
                <EmptyState title="Belum ada satu pun ambang stok yang diisi"
                  description="Selama ambang minimum kosong, sistem tidak bisa tahu barang apa yang perlu dibeli. Isi ambangnya massal dulu — dari lot pembelian nyata, persen stok, atau angka yang Anda tentukan."
                  action={<Button onClick={() => goto('wh-master', 'thresholds')} data-testid="shopping-empty-cta">Isi ambang massal</Button>} />
              ) : (
                <EmptyState title="Tidak ada yang perlu dibeli minggu ini"
                  description={`Semua barang yang sudah punya ambang stoknya masih di atas ambang.${summary && summary.without_threshold > 0
                    ? ` Catatan: ${summary.without_threshold} barang belum berambang, jadi daftar ini belum lengkap.` : ''}`} />
              )}
            </div>
          ) : (
            <Table data-testid="shopping-table">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <Checkbox checked={semuaTercentang} onCheckedChange={toggleAll} disabled={!selectable.length}
                      aria-label="Pilih semua barang yang belum ber-PR" data-testid="shopping-select-all" />
                  </TableHead>
                  <TableHead>Barang</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Stok</TableHead>
                  <TableHead className="text-right">Ambang</TableHead>
                  <TableHead className="text-right">Kurang</TableHead>
                  <TableHead className="text-right">Qty beli</TableHead>
                  <TableHead className="text-right">Harga</TableHead>
                  <TableHead className="text-right">Perkiraan total</TableHead>
                  <TableHead>Supplier</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map(r => {
                  const meta = STATUS_META[r.stock_status] || STATUS_META.low;
                  const isSel = selected.has(r.material_id);
                  return (
                    <TableRow key={r.material_id} className={isSel ? 'bg-primary/5' : undefined} data-testid={`shopping-row-${r.code}`}>
                      <TableCell>
                        <Checkbox checked={isSel} disabled={r.already_requested} onCheckedChange={() => toggle(r.material_id)}
                          aria-label={`Pilih ${r.code}`} data-testid={`shopping-check-${r.code}`} />
                      </TableCell>
                      <TableCell className="min-w-[11rem]">
                        <div className="tabular-nums text-xs text-muted-foreground">{r.code}</div>
                        <div className="text-foreground">{r.name}</div>
                        <div className="text-xs text-muted-foreground">{jenisLabel(r.type)} · {r.base_uom}</div>
                      </TableCell>
                      <TableCell>
                        {r.already_requested ? (
                          <span data-testid={`shopping-pr-flag-${r.code}`} title={`Dibuat ${String((r.pr || {}).created_at || '').slice(0, 10)}`}>
                            <StatusBadge status="ber-pr" label={(r.pr || {}).number || 'Sudah diminta'} tone="info" />
                          </span>
                        ) : (
                          <StatusBadge status={r.stock_status} label={meta.label} tone={meta.tone} />
                        )}
                        {!r.valued && <span className="mt-0.5 block text-xs text-[hsl(var(--warning-text))]">belum berharga</span>}
                      </TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap">{num(r.onhand)} {r.base_uom}</TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap">
                        {num(r.alert_at)}
                        <span className="block text-xs text-muted-foreground" title={r.threshold_basis_note || ''}>{keteranganAmbang(r)}</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap text-[hsl(var(--danger-text))]">
                        {num(r.shortage)}
                        {Number(r.incoming_po_qty || 0) > 0 && (
                          <span className="block text-xs text-muted-foreground" data-testid={`shopping-incoming-${r.code}`}>
                            sisa PO {num(r.incoming_po_qty)} {r.base_uom}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap" data-testid={`shopping-qty-${r.code}`}>
                        <span className="tabular-nums font-medium">{num(r.qty_buy)} {r.purchase_uom}</span>
                        {r.purchase_factor !== 1 && (
                          <span className="block text-xs text-muted-foreground">= {num(r.qty_buy_base)} {r.base_uom}</span>
                        )}
                        {r.qty_note && <span className="block text-xs text-[hsl(var(--warning-text))]">{r.qty_note}</span>}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        {r.valued ? (
                          <>
                            <span className="tabular-nums">{rp(r.price_per_purchase_uom)}</span>
                            <span className="block text-xs text-muted-foreground">
                              /{r.purchase_uom} · {r.price_source === 'supplier_price_list' ? 'harga supplier' : 'HPP pembelian'}
                            </span>
                          </>
                        ) : (
                          <span className="text-xs text-[hsl(var(--warning-text))]">belum ada harga</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums font-medium whitespace-nowrap" data-testid={`shopping-total-${r.code}`}>
                        {r.valued ? rp(r.est_total) : '—'}
                      </TableCell>
                      <TableCell className="min-w-[9rem] text-sm">
                        {r.supplier ? (
                          <>
                            <span className="text-foreground">{r.supplier.name}</span>
                            <span className="block text-xs text-muted-foreground">
                              {rp(r.supplier.price)}/{r.supplier.uom}
                              {r.supplier.moq > 0 ? ` · MOQ ${num(r.supplier.moq)}` : ''}
                              {r.supplier.lead_time_days ? ` · ${r.supplier.lead_time_days} hari` : ''}
                            </span>
                          </>
                        ) : (
                          <span className="text-xs text-muted-foreground">belum ada daftar harga</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}

          {summary && rows.length > 0 && (
            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                {summary.unvalued_note} Qty beli dibulatkan ke atas ke satuan beli, dan dinaikkan
                ke MOQ supplier bila ada — alasannya tertulis di baris masing-masing.
                {/* 2026-11-06 (Tahap 2): PR/PO terbuka dibaca tanpa batas minggu; sisa PO mengurangi kekurangan */}
                {' '}Sisa PO yang masih terbuka (dari minggu mana pun) mengurangi kekurangan.
                {summary.already_requested_count > 0
                  && ` ${summary.already_requested_count} barang sudah tertutup PO terbuka atau punya PR terbuka dan tidak dihitung lagi (anti dobel belanja).`}
              </span>
            </p>
          )}
        </div>)}

        {tab === 'history' && (<div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {history?.summary
              ? `${history.summary.requests} PR · total ${rp(history.summary.total_value)}`
              : 'Memuat…'}
          </p>
          {history && (
            <TabelData kolom={kolomRiwayat} baris={history.items || []} kunci={(h) => h.id} testId="shopping-history-table"
              kosong={<EmptyState title="Belum ada PR yang dibuat dari Belanja mingguan" />} />
          )}
        </div>)}

        <FormPopup open={dialogOpen} onClose={() => setDialogOpen(false)} ukuran="panjang" testId="shopping-pr-dialog"
          judul={`Buat permintaan pengadaan · ${chosen.length} barang`}
          keterangan="PR dibuat berstatus draf — belum dikirim ke persetujuan. Kirimnya dari Portal Pengadaan → Permintaan Pengadaan."
          onSimpan={createPR} menyimpan={creating} bisaSimpan={chosen.length > 0}
          labelSimpan={`Buat PR (${chosen.length} barang)`}>
          <div className="max-h-64 overflow-auto rounded-md border border-[var(--glass-border)]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Barang</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Harga</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {chosen.map(c => (
                  <TableRow key={c.material_id}>
                    <TableCell><span className="tabular-nums text-xs text-muted-foreground">{c.code}</span> {c.name}</TableCell>
                    <TableCell className="text-right tabular-nums">{num(c.qty_buy)} {c.purchase_uom}</TableCell>
                    <TableCell className="text-right tabular-nums">{c.valued ? rp(c.price_per_purchase_uom) : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{c.valued ? rp(c.est_total) : '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Perkiraan nilai PR</span>
            <span className="font-semibold tabular-nums text-foreground" data-testid="shopping-dialog-total">{rp(chosenTotal)}</span>
          </div>
          {chosen.some(c => !c.valued) && (
            <p className="text-xs text-[hsl(var(--warning-text))]">
              Ada barang tanpa harga — barisnya tetap masuk PR dengan harga 0 supaya bagian
              pengadaan mengisi harga penawaran, tetapi tidak dihitung ke perkiraan nilai.
            </p>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Dibutuhkan sebelum" petunjuk="Opsional">
              <DatePicker value={neededBy} onChange={setNeededBy} placeholder="Tidak ditentukan" testId="shopping-needed-by" />
            </Isian>
            <Isian label="Catatan" petunjuk="Opsional" htmlFor="shopping-notes-in">
              <Input id="shopping-notes-in" value={notes} onChange={e => setNotes(e.target.value)}
                placeholder="mis. dipakai untuk order cutting minggu depan" data-testid="shopping-notes" />
            </Isian>
          </div>
        </FormPopup>
      </PageLayout>
  );
}

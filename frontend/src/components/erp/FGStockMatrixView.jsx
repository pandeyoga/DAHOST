import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  RefreshCw, Search, MinusCircle, Lock, ChevronDown, ChevronRight, Sparkles,
} from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { useToast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';
import { formatDateID } from '@/lib/format';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';

const pcs = (n) => Number(n || 0).toLocaleString('id-ID');

/**
 * FG Stock Matrix viewer — pivots inventory by Model × Color (rows) × Size (columns).
 * Interactive: cell click opens detail popup with allocate/issue actions.
 *
 * Standar UI/UX v2 (8 Nov 2026): penyaring satu baris tanpa panel abu, kartu angka = StatTile (disembunyikan bila
 * semuanya 0 → tampilan kosong), detail sel = DetailPopup, reservasi = FormPopup pendek, unduh Excel/CSV per sel.
 * Kartu "Size range" dihapus: isinya daftar ukuran global (bukan ukuran yang punya stok) — menyesatkan.
 * Titik warna dihapus: banyak nama warna dipetakan ke token yang salah (PINK → ungu, BROWN → kuning).
 */
export default function FGStockMatrixView({ token, onCellAction }) {
  const { toast } = useToast();
  const [matrix, setMatrix] = useState({ summary: {}, size_order: [], models: [] });
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterModel, setFilterModel] = useState('all');
  const [onlyWithStock, setOnlyWithStock] = useState(true);
  const [collapsedModels, setCollapsedModels] = useState({});
  const [detailCell, setDetailCell] = useState(null); // { material_id, code, ... }
  const [actionMode, setActionMode] = useState(null); // 'allocate' | null
  const [actionQty, setActionQty] = useState('');
  const [actionRef, setActionRef] = useState('');
  const [actionNotes, setActionNotes] = useState('');
  const [actionSubmitting, setActionSubmitting] = useState(false);
  const [detailData, setDetailData] = useState(null);

  const h = useMemo(() => ({
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  }), [token]);

  const fetchMatrix = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (onlyWithStock) params.set('only_with_stock', 'true');
      if (filterModel && filterModel !== 'all') params.set('model', filterModel);

      const [mRes, modelsRes] = await Promise.all([
        fetch(`/api/rahaza/fg-matrix?${params}`, { headers: h }),
        fetch('/api/rahaza/fg-matrix/models', { headers: h }),
      ]);
      if (mRes.ok) {
        const data = await mRes.json();
        setMatrix(data);
      }
      if (modelsRes.ok) setModels(await modelsRes.json());
    } catch (e) {
      toast({ title: 'Gagal memuat matriks', description: e.message, variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [h, onlyWithStock, filterModel, toast]);

  useEffect(() => { fetchMatrix(); }, [fetchMatrix]);

  const fetchCellDetail = useCallback(async (materialId) => {
    try {
      const res = await fetch(`/api/rahaza/fg-matrix/cell-detail/${materialId}`, { headers: h });
      if (res.ok) setDetailData(await res.json());
    } catch (e) {
      console.error(e);
    }
  }, [h]);

  const openCell = (cell, modelKey) => {
    setDetailCell({ ...cell, model_key: modelKey });
    setActionMode(null);
    setActionQty('');
    setActionRef('');
    setActionNotes('');
    setDetailData(null);
    if (cell.material_id) fetchCellDetail(cell.material_id);
  };

  const closeDetail = () => {
    setDetailCell(null);
    setActionMode(null);
  };

  const handleAllocate = async () => {
    if (!detailCell?.material_id) return;
    const qty = parseInt(actionQty, 10);
    if (!qty || qty <= 0) return toast({ title: 'Qty harus lebih dari 0', variant: 'destructive' });
    if (qty > detailCell.available) return toast({ title: `Maksimal: ${detailCell.available} pcs`, variant: 'destructive' });

    setActionSubmitting(true);
    try {
      const res = await fetch('/api/rahaza/fg-matrix/allocate', {
        method: 'POST',
        headers: h,
        body: JSON.stringify({
          material_id: detailCell.material_id,
          qty,
          reference_type: 'manual',
          reference_label: actionRef || `Allocation for ${detailCell.code}`,
          notes: actionNotes,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Reservasi gagal');
      toast({ title: `Direservasi ${qty} pcs — ${data.reservation_no}` });
      setActionMode(null);
      setActionQty('');
      setActionRef('');
      setActionNotes('');
      fetchMatrix();
      fetchCellDetail(detailCell.material_id);
    } catch (e) {
      toast({ title: e.message, variant: 'destructive' });
    } finally {
      setActionSubmitting(false);
    }
  };

  const handleRelease = async (reservationId) => {
    try {
      const res = await fetch(`/api/rahaza/fg-matrix/release/${reservationId}`, {
        method: 'POST', headers: h,
      });
      if (!res.ok) throw new Error('Gagal melepas reservasi');
      toast({ title: 'Reservasi dilepas' });
      fetchMatrix();
      if (detailCell?.material_id) fetchCellDetail(detailCell.material_id);
    } catch (e) {
      toast({ title: e.message, variant: 'destructive' });
    }
  };

  const handleSeedDemo = async () => {
    try {
      const res = await fetch('/api/rahaza/fg-matrix/seed-demo', { method: 'POST', headers: h });
      const data = await res.json();
      if (data.status === 'seeded') {
        toast({ title: `Data contoh ditambahkan: ${data.materials_inserted} SKU` });
      } else {
        toast({ title: 'Data contoh sudah ada' });
      }
      fetchMatrix();
    } catch (e) {
      toast({ title: e.message, variant: 'destructive' });
    }
  };

  const toggleModel = (key) => setCollapsedModels(s => ({ ...s, [key]: !s[key] }));

  const filteredModels = useMemo(() => {
    if (!search) return matrix.models;
    const q = search.toLowerCase();
    return matrix.models.filter(m =>
      m.model_key.toLowerCase().includes(q) ||
      m.colors.some(c => c.toLowerCase().includes(q)) ||
      Object.values(m.cells).some(row =>
        Object.values(row).some(cell => (cell.code || '').toLowerCase().includes(q) || (cell.name || '').toLowerCase().includes(q))
      )
    );
  }, [matrix.models, search]);

  // Baris unduhan: satu baris per sel (model · warna · ukuran) dari model yang tampil.
  const barisUnduh = useMemo(() => {
    const out = [];
    filteredModels.forEach((m) => m.colors.forEach((color) => m.sizes.forEach((size) => {
      const c = m.cells[color]?.[size];
      if (c) out.push({ model: m.model_key, color, size, ...c });
    })));
    return out;
  }, [filteredModels]);

  // Intensitas sel (token warna) — makin banyak stok makin pekat.
  const cellIntensity = (qty, max) => {
    if (qty <= 0) return 'text-muted-foreground';
    const ratio = max > 0 ? qty / max : 0;
    if (ratio < 0.5) return 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success-text))] border-[hsl(var(--success)/0.35)]';
    if (ratio < 0.75) return 'bg-[hsl(var(--success)/0.22)] text-[hsl(var(--success-text))] border-[hsl(var(--success)/0.5)]';
    return 'bg-[hsl(var(--success)/0.32)] text-foreground border-[hsl(var(--success)/0.6)]';
  };

  const s = matrix.summary || {};
  const adaAngka = Number(s.total_models || 0) || Number(s.total_skus || 0) || Number(s.total_qty || 0);

  return (
    <div className="space-y-4" data-testid="fg-matrix-view">
      {/* Penyaring (satu baris) */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari model, warna, atau SKU" className="pl-8" value={search}
            onChange={e => setSearch(e.target.value)} data-testid="fg-matrix-search" />
        </div>
        <SmartNativeSelect value={filterModel} onChange={e => setFilterModel(e.target.value)} className="w-48"
          aria-label="Model" data-testid="fg-matrix-model-filter">
          <option value="all">Semua model</option>
          {models.map(m => <option key={m} value={m}>{m}</option>)}
        </SmartNativeSelect>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
          <Checkbox checked={onlyWithStock} onCheckedChange={(v) => setOnlyWithStock(!!v)} data-testid="fg-matrix-stock-toggle" />
          Hanya yang ada stok
        </label>
        <div className="ml-auto flex items-center gap-2">
          {matrix.models.length === 0 && (
            <Button variant="outline" onClick={handleSeedDemo} data-testid="fg-matrix-seed-btn">
              <Sparkles />Isi data contoh
            </Button>
          )}
          <TombolUnduh namaBerkas="matriks-produk-jadi" namaLembar="Matriks" baris={barisUnduh} testId="fg-matrix-unduh"
            kolom={[
              { label: 'Model', nilai: (r) => r.model },
              { label: 'Warna', nilai: (r) => r.color },
              { label: 'Ukuran', nilai: (r) => r.size },
              { label: 'SKU', nilai: (r) => r.code },
              { label: 'Nama', nilai: (r) => r.name },
              { label: 'Stok (pcs)', nilai: (r) => Number(r.qty || 0) },
              { label: 'Direservasi (pcs)', nilai: (r) => Number(r.reserved || 0) },
              { label: 'Tersedia (pcs)', nilai: (r) => Number(r.available || 0) },
            ]} />
          <Button variant="outline" size="icon" onClick={fetchMatrix} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </div>

      {/* Ringkasan — disembunyikan bila semuanya 0 (tampilan kosong menjelaskan) */}
      {adaAngka ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Model" value={pcs(s.total_models)} sub={onlyWithStock ? 'yang punya stok' : 'semua model'} />
          <StatTile label="SKU" value={pcs(s.total_skus)} sub={onlyWithStock ? 'yang punya stok' : 'semua SKU produk jadi'} />
          <StatTile label="Total stok" value={pcs(s.total_qty)} suffix="pcs" accent={Number(s.total_qty) < 0 ? 'danger' : 'default'}
            sub="jumlah semua sel di matriks" />
        </div>
      ) : null}

      {loading && (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat matriks…</p>
      )}
      {!loading && filteredModels.length === 0 && (
        <EmptyState
          title={matrix.models.length === 0
            ? (onlyWithStock ? 'Belum ada produk jadi yang punya stok' : 'Belum ada data produk jadi')
            : 'Tidak ada model yang cocok dengan saringan'}
          description={matrix.models.length === 0 && onlyWithStock
            ? 'Lepas centang "Hanya yang ada stok" untuk melihat semua model.' : undefined} />
      )}

      {/* Matriks per model */}
      {!loading && filteredModels.map(model => {
        const isCollapsed = collapsedModels[model.model_key];
        // Compute max qty within this model's cells for heatmap intensity
        let maxQty = 0;
        Object.values(model.cells).forEach(row => Object.values(row).forEach(c => { if (c.qty > maxQty) maxQty = c.qty; }));

        return (
          <GlassCard key={model.model_key} className="overflow-hidden p-0" data-testid={`fg-matrix-model-${model.model_key}`}>
            <div className="flex items-center gap-2 border-b border-[var(--glass-border)] px-3 py-2">
              <Button variant="ghost" size="icon" onClick={() => toggleModel(model.model_key)}
                aria-expanded={!isCollapsed} title={isCollapsed ? 'Buka matriks' : 'Tutup matriks'}
                aria-label={isCollapsed ? `Buka matriks ${model.model_key}` : `Tutup matriks ${model.model_key}`}>
                {isCollapsed ? <ChevronRight /> : <ChevronDown />}
              </Button>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-foreground">
                  {model.model_key} <span className="font-normal text-muted-foreground">· {model.sku_count} SKU</span>
                </p>
                <p className="text-xs text-muted-foreground">
                  {model.colors.length} warna × {model.sizes.length} ukuran · total {pcs(model.total_qty)} pcs
                  {model.total_available !== model.total_qty && <> · {pcs(model.total_available)} tersedia</>}
                </p>
              </div>
            </div>

            {!isCollapsed && (
              <Table stickyFirstCol>
                <TableHeader>
                  <TableRow>
                    <TableHead className="min-w-[8rem]">Warna \ ukuran</TableHead>
                    {model.sizes.map(size => (
                      <TableHead key={size} className="min-w-[5rem] text-center">{size}</TableHead>
                    ))}
                    <TableHead className="text-right">Subtotal</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {model.colors.map(color => {
                    const row = model.cells[color] || {};
                    const subtotal = Object.values(row).reduce((a, c) => a + (c.qty || 0), 0);
                    return (
                      <TableRow key={color}>
                        <TableCell className="font-medium">{color}</TableCell>
                        {model.sizes.map(size => {
                          const cell = row[size];
                          if (!cell) {
                            return <TableCell key={size} className="text-center text-muted-foreground">—</TableCell>;
                          }
                          return (
                            <TableCell key={size} className="p-1.5 text-center">
                              <Button variant="outline" size="sm" onClick={() => openCell(cell, model.model_key)}
                                className={cn('h-auto w-full flex-col gap-0 py-1 tabular-nums', cellIntensity(cell.qty, maxQty))}
                                data-testid={`fg-matrix-cell-${cell.code}`}
                                title={`${cell.code} · ${cell.name} · stok ${cell.qty}, direservasi ${cell.reserved}, tersedia ${cell.available}`}>
                                <span className="text-sm font-semibold">{cell.qty}</span>
                                {cell.reserved > 0 && (
                                  <span className="inline-flex items-center gap-0.5 text-xs font-normal">
                                    <Lock className="!h-3 !w-3" />{cell.reserved}
                                  </span>
                                )}
                              </Button>
                            </TableCell>
                          );
                        })}
                        <TableCell className="text-right font-semibold tabular-nums">{pcs(subtotal)}</TableCell>
                      </TableRow>
                    );
                  })}
                  <TableRow>
                    <TableCell className="text-xs font-semibold text-muted-foreground">Total per ukuran</TableCell>
                    {model.sizes.map(size => {
                      const total = model.colors.reduce((a, c) => a + (model.cells[c]?.[size]?.qty || 0), 0);
                      return <TableCell key={size} className="text-center font-semibold tabular-nums">{pcs(total)}</TableCell>;
                    })}
                    <TableCell className="text-right font-bold tabular-nums">{pcs(model.total_qty)}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            )}
          </GlassCard>
        );
      })}

      {/* Detail sel (popup) */}
      {detailCell && (
        <DetailPopup open onClose={closeDetail} judul={detailCell.code} testId="fg-matrix-cell-modal"
          keterangan={`${detailCell.name || ''}${detailCell.model_key ? ` · model ${detailCell.model_key}` : ''}`}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => setActionMode('allocate')} disabled={detailCell.available <= 0}
              data-testid="fg-matrix-btn-allocate"><Lock />Reservasi</Button>
            <Button size="sm" variant="outline" disabled={detailCell.available <= 0} data-testid="fg-matrix-btn-issue"
              onClick={() => { closeDetail(); onCellAction?.('issue', detailCell); }}>
              <MinusCircle />Keluarkan stok
            </Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Stok"><span className="tabular-nums">{pcs(detailCell.qty)} pcs</span></BarisDetail>
            <BarisDetail label="Direservasi"><span className="tabular-nums">{pcs(detailCell.reserved)} pcs</span></BarisDetail>
            <BarisDetail label="Tersedia"><span className="tabular-nums font-medium">{pcs(detailCell.available)} pcs</span></BarisDetail>
          </dl>

          {!detailData ? (
            <p className="text-sm text-muted-foreground">Memuat rincian…</p>
          ) : (
            <>
              {detailData.stocks_by_location?.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium text-foreground">Stok per lokasi</p>
                  <Table>
                    <TableHeader><TableRow><TableHead>Lokasi</TableHead><TableHead className="text-right">Qty (pcs)</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {detailData.stocks_by_location.map((sl, idx) => (
                        <TableRow key={idx}>
                          <TableCell>{sl.location_name || sl.location_id || 'Bawaan'}</TableCell>
                          <TableCell className="text-right tabular-nums">{pcs(sl.qty)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}

              {detailData.active_reservations?.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium text-foreground">Reservasi aktif</p>
                  <Table>
                    <TableHeader><TableRow><TableHead>No. reservasi</TableHead><TableHead>Untuk</TableHead><TableHead className="text-right">Qty (pcs)</TableHead><TableHead /></TableRow></TableHeader>
                    <TableBody>
                      {detailData.active_reservations.map(r => (
                        <TableRow key={r.id}>
                          <TableCell className="tabular-nums">{r.reservation_no}</TableCell>
                          <TableCell className="text-muted-foreground">{r.reference_label || '—'}</TableCell>
                          <TableCell className="text-right tabular-nums">{pcs(r.qty)}</TableCell>
                          <TableCell className="text-right">
                            <Button size="sm" variant="outline" onClick={() => handleRelease(r.id)}
                              data-testid={`fg-matrix-release-${r.reservation_no}`}>Lepas</Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}

              {detailData.recent_movements?.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium text-foreground">Pergerakan terakhir</p>
                  <Table>
                    <TableHeader><TableRow><TableHead>Tanggal</TableHead><TableHead>Arah</TableHead><TableHead>Keterangan</TableHead><TableHead className="text-right">Qty (pcs)</TableHead></TableRow></TableHeader>
                    <TableBody>
                      {detailData.recent_movements.slice(0, 5).map(mv => (
                        <TableRow key={mv.id}>
                          <TableCell className="whitespace-nowrap">{formatDateID(mv.timestamp)}</TableCell>
                          <TableCell>{mv.direction === 'in'
                            ? <StatusBadge status="masuk" label="Masuk" tone="success" />
                            : <StatusBadge status="keluar" label="Keluar" tone="danger" />}</TableCell>
                          <TableCell className="text-muted-foreground">{mv.notes || mv.reason_label || '—'}</TableCell>
                          <TableCell className="text-right tabular-nums">{mv.direction === 'in' ? '' : '−'}{pcs(mv.qty)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </>
          )}
        </DetailPopup>
      )}

      {/* Reservasi stok (form popup pendek) */}
      <FormPopup open={!!detailCell && actionMode === 'allocate'} onClose={() => setActionMode(null)}
        judul="Reservasi stok" keterangan={detailCell ? `${detailCell.code} · tersedia ${pcs(detailCell.available)} pcs` : undefined}
        testId="fg-matrix-allocate-form" onSimpan={handleAllocate} menyimpan={actionSubmitting} labelSimpan="Simpan reservasi"
        bisaSimpan={!!actionQty && parseInt(actionQty, 10) > 0 && parseInt(actionQty, 10) <= (detailCell?.available || 0)}>
        <Isian label="Qty (pcs)" wajib htmlFor="fg-alloc-qty">
          <Input id="fg-alloc-qty" type="number" min="1" max={detailCell?.available} value={actionQty}
            onChange={e => setActionQty(e.target.value)} placeholder={`Maks ${detailCell?.available ?? 0} pcs`}
            data-testid="fg-matrix-allocate-qty" />
        </Isian>
        <Isian label="Untuk (referensi)" htmlFor="fg-alloc-ref">
          <Input id="fg-alloc-ref" value={actionRef} onChange={e => setActionRef(e.target.value)}
            placeholder="Contoh: PO-2026-001 / Customer XYZ" data-testid="fg-matrix-allocate-ref" />
        </Isian>
        <Isian label="Catatan" htmlFor="fg-alloc-notes">
          <Input id="fg-alloc-notes" value={actionNotes} onChange={e => setActionNotes(e.target.value)} placeholder="Catatan tambahan" />
        </Isian>
      </FormPopup>
    </div>
  );
}

export { FGStockMatrixView };

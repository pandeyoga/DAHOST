import { useState, useEffect, useMemo } from 'react';
import {
  Calculator, Download, Plus, Trash2, AlertTriangle, Layers,
  ChevronDown, ChevronRight, Loader2, PackageSearch, CheckCircle2, Wallet,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassPanel, GlassInput } from '@/components/ui/glass';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { toast } from 'sonner';
import SearchableSelect from './engine/SearchableSelect';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { apiGet, apiPost } from '../../lib/api';
import { readNumber, FIELD } from '@/lib/materialFields';  // FASE 6.6-B

/**
 * RahazaMaterialRequirementsModule — Fase 5 (Master Product): Laporan Kebutuhan Material.
 *
 * Agregasi kebutuhan material lintas banyak baris produksi (model × size × qty) via
 * POST /api/rahaza/material-requirements. Dua mode input:
 *   1. "Dari PO Produksi": pilih PO internal → item-nya jadi baris otomatis.
 *   2. "Manual": susun baris {model, size, qty} sendiri.
 * Menampilkan tabel agregat (total kebutuhan + stok on-hand + kekurangan), ringkasan,
 * rincian per-baris, dan export CSV.
 */

const fmt = (n, dp = 3) => {
  const v = Number(n);
  if (!isFinite(v)) return '0';
  return Number.isInteger(v) ? String(v) : v.toFixed(dp);
};

const rp = (n) => {
  const v = Number(n);
  if (!isFinite(v)) return '—';
  return 'Rp' + Math.round(v).toLocaleString('id-ID');
};

const emptyLine = () => ({ model_id: '', size_id: '', qty_pcs: '' });

export default function RahazaMaterialRequirementsModule() {
  const [mode, setMode] = useState('po');            // 'po' | 'manual'
  const [models, setModels] = useState([]);
  const [sizes, setSizes] = useState([]);
  // {model_id: Set(size_id)} dari varian aktif — ukuran baris manual mengikuti model (2026-11-07)
  const [modelSizes, setModelSizes] = useState({});
  const [pos, setPos] = useState([]);
  const [poId, setPoId] = useState('');
  const [lines, setLines] = useState([emptyLine()]);
  const [rounding, setRounding] = useState('none');
  const [includeStock, setIncludeStock] = useState(true);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [showBreakdown, setShowBreakdown] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [m, s, v] = await Promise.all([
          apiGet('/rahaza/models?active=true&limit=500'),
          apiGet('/rahaza/sizes?active=true&limit=100'),
          apiGet('/rahaza/variants').catch(() => []),
        ]);
        // server mengembalikan model non-aktif juga (penanda `active`) — yang non-aktif tidak ditawarkan
        setModels((Array.isArray(m) ? m : (m?.items || [])).filter(x => x.active !== false));
        setSizes((Array.isArray(s) ? s : (s?.items || [])).filter(x => x.active !== false));
        const per = {};
        (Array.isArray(v) ? v : []).forEach(x => {
          if (x.model_id && x.size_id) (per[x.model_id] = per[x.model_id] || new Set()).add(x.size_id);
        });
        setModelSizes(per);
      } catch (e) { /* non-fatal */ }
      try {
        const env = await apiGet('/production-pos?business_type=internal&per_page=200&sort_by=created_at&sort_dir=desc');
        const items = Array.isArray(env?.items) ? env.items : (Array.isArray(env) ? env : []);
        setPos(items);
      } catch (e) { setPos([]); }
    })();
  }, []);

  const modelOptions = useMemo(
    () => models.map(m => ({ value: m.id, label: `${m.code} · ${m.name}`, sub: m.category || '' })),
    [models],
  );
  const sizeOptions = useMemo(
    () => sizes.map(s => ({ value: s.id, label: s.code, sub: s.name && s.name !== s.code ? s.name : '' })),
    [sizes],
  );
  // Ukuran yang ditawarkan = ukuran varian model itu; model tanpa varian → semua ukuran master.
  const sizeOptionsFor = (modelId) => {
    const own = modelSizes[modelId];
    return own && own.size ? sizeOptions.filter(o => own.has(o.value)) : sizeOptions;
  };
  const poOptions = useMemo(
    () => pos.map(p => ({
      value: p.id,
      label: `${p.po_number} · ${p.customer_name || 'Internal'}`,
      sub: `${(p.items?.length ?? p.item_count ?? '')} item · ${p.status || ''}`,
    })),
    [pos],
  );

  const addLine = () => setLines(ls => [...ls, emptyLine()]);
  const removeLine = (idx) => setLines(ls => ls.filter((_, i) => i !== idx));
  const updateLine = (idx, field, value) =>
    setLines(ls => ls.map((l, i) => {
      if (i !== idx) return l;
      const next = { ...l, [field]: value };
      // ganti model → ukuran yang bukan milik model baru dilepas
      if (field === 'model_id' && l.size_id) {
        const own = modelSizes[value];
        if (own && own.size && !own.has(l.size_id)) next.size_id = '';
      }
      return next;
    }));

  const compute = async () => {
    let body = { rounding, include_stock: includeStock };
    if (mode === 'po') {
      if (!poId) { toast.error('Pilih PO produksi dulu'); return; }
      body.po_id = poId;
    } else {
      const clean = lines
        .filter(l => l.model_id && l.size_id && Number(l.qty_pcs) > 0)
        .map(l => ({ model_id: l.model_id, size_id: l.size_id, qty_pcs: Number(l.qty_pcs) }));
      if (clean.length === 0) { toast.error('Isi minimal 1 baris (model + size + qty > 0)'); return; }
      body.lines = clean;
    }
    setLoading(true);
    setResult(null);
    try {
      const data = await apiPost('/rahaza/material-requirements', body);
      setResult(data);
      const short = data?.totals?.total_shortfall_lines || 0;
      if ((data?.aggregated || []).length === 0) {
        toast.warning('Tidak ada kebutuhan material terhitung (cek BOM model/size).');
      } else if (short > 0) {
        toast.warning(`${short} material kekurangan stok.`);
      } else {
        toast.success('Kebutuhan material dihitung.');
      }
    } catch (e) {
      toast.error(e.message || 'Gagal menghitung kebutuhan material');
    } finally {
      setLoading(false);
    }
  };

  const exportCSV = () => {
    if (!result) return;
    const withStock = result.include_stock;
    const withCost = result.include_cost;
    const byPo = result.source === 'po';
    const head = ['Kode', 'Nama', 'Kategori', 'Tipe', 'Total Kebutuhan', 'Unit'];
    if (byPo) head.push('Sudah keluar', 'Sisa kebutuhan');
    if (withCost) head.push('Harga Satuan', 'Subtotal');
    if (withStock) head.push('On-hand', 'Tersedia', 'Kekurangan');
    let csv = head.join(',') + '\n';
    (result.aggregated || []).forEach(m => {
      const row = [
        m.code || '',
        `"${(m.name || '').replace(/"/g, '""')}"`,
        `"${(m.category_name || '').replace(/"/g, '""')}"`,
        m.material_type || '',
        m.total_required,
        m.unit || '',
      ];
      if (byPo) row.push(m.issued ?? 0, m.remaining_required ?? m.total_required);
      if (withCost) row.push(m.unit_cost ?? '', m.subtotal_cost ?? '');
      if (withStock) row.push(m.onhand ?? '', m.available ?? '', m.shortfall ?? '');
      csv += row.join(',') + '\n';
    });
    if (withCost) {
      const tail = new Array(head.length).fill('');
      tail[0] = 'GRAND TOTAL';
      tail[head.indexOf('Subtotal')] = result.totals?.grand_total_cost ?? '';
      csv += tail.join(',') + '\n';
    }
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const tag = result.source === 'po' ? (result.po?.po_number || 'po') : 'manual';
    a.download = `kebutuhan-material-${tag}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
    toast.success('CSV berhasil diunduh');
  };

  const t = result?.totals;
  const agg = result?.aggregated || [];
  const noBom = result?.lines_without_bom || [];
  const resolved = result?.lines_resolved || [];

  return (
    <div className="space-y-5" data-testid="material-requirements-module">
      <div>
        <h2 className="text-xl font-bold text-foreground flex items-center gap-2">
          <Calculator className="w-5 h-5 text-primary" />
          Laporan Kebutuhan Material
        </h2>
        <p className="text-sm text-muted-foreground mt-0.5">
          Hitung total kebutuhan material (agregasi BOM) untuk satu PO produksi atau sekumpulan
          model &amp; ukuran — lengkap dengan stok on-hand dan kekurangan untuk perencanaan pembelian.
        </p>
      </div>

      {/* Input card */}
      <GlassPanel className="p-5 space-y-4">
        {/* Mode toggle */}
        <div className="flex items-center gap-2" data-testid="mrp-mode-toggle">
          <button
            type="button"
            onClick={() => { setMode('po'); setResult(null); }}
            data-testid="mrp-mode-po"
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors border ${
              mode === 'po'
                ? 'bg-primary text-primary-foreground border-primary'
                : 'bg-transparent text-foreground/70 border-[var(--glass-border)] hover:bg-foreground/5'
            }`}
          >
            Dari PO Produksi
          </button>
          <button
            type="button"
            onClick={() => { setMode('manual'); setResult(null); }}
            data-testid="mrp-mode-manual"
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors border ${
              mode === 'manual'
                ? 'bg-primary text-primary-foreground border-primary'
                : 'bg-transparent text-foreground/70 border-[var(--glass-border)] hover:bg-foreground/5'
            }`}
          >
            Manual (Model + Ukuran)
          </button>
        </div>

        {mode === 'po' ? (
          <div className="max-w-xl" data-testid="mrp-po-picker">
            <label className="block text-sm font-medium text-foreground/70 mb-1.5">
              PO Produksi Internal
            </label>
            <SearchableSelect
              options={poOptions}
              value={poId}
              onChange={setPoId}
              placeholder={pos.length ? '— Pilih PO —' : 'Belum ada PO internal'}
              data-testid="mrp-po-select"
            />
            <p className="text-xs text-muted-foreground mt-1">
              Item PO otomatis dijadikan baris kebutuhan (model + ukuran + qty).
            </p>
          </div>
        ) : (
          <div className="space-y-2" data-testid="mrp-manual-lines">
            <div className="grid grid-cols-12 gap-2 text-xs font-medium text-foreground/50 px-1">
              <div className="col-span-6">Model</div>
              <div className="col-span-3">Ukuran</div>
              <div className="col-span-2">Qty (pcs)</div>
              <div className="col-span-1" />
            </div>
            {lines.map((l, idx) => (
              <div className="grid grid-cols-12 gap-2 items-center" key={idx} data-testid={`mrp-line-${idx}`}>
                <div className="col-span-6">
                  <SearchableSelect
                    options={modelOptions}
                    value={l.model_id}
                    onChange={v => updateLine(idx, 'model_id', v)}
                    placeholder="— Pilih Model —"
                    data-testid={`mrp-line-model-${idx}`}
                  />
                </div>
                <div className="col-span-3">
                  <SearchableSelect
                    options={sizeOptionsFor(l.model_id)}
                    value={l.size_id}
                    onChange={v => updateLine(idx, 'size_id', v)}
                    placeholder={l.model_id ? '— Ukuran —' : 'Pilih model dulu'}
                    disabled={!l.model_id}
                    data-testid={`mrp-line-size-${idx}`}
                  />
                </div>
                <div className="col-span-2">
                  <GlassInput
                    type="number"
                    min="0"
                    placeholder="0"
                    value={l.qty_pcs}
                    onChange={e => updateLine(idx, 'qty_pcs', e.target.value)}
                    data-testid={`mrp-line-qty-${idx}`}
                  />
                </div>
                <div className="col-span-1 flex justify-center">
                  <button
                    type="button"
                    onClick={() => removeLine(idx)}
                    disabled={lines.length === 1}
                    className="text-foreground/40 hover:text-[hsl(var(--destructive))] disabled:opacity-30 transition-colors"
                    data-testid={`mrp-line-remove-${idx}`}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={addLine} data-testid="mrp-add-line">
              <Plus className="w-4 h-4 mr-1.5" /> Tambah Baris
            </Button>
          </div>
        )}

        {/* Options + compute */}
        <div className="flex flex-wrap items-end gap-4 pt-2 border-t border-[var(--glass-border)]">
          <div>
            <label className="block text-xs font-medium text-foreground/60 mb-1">Pembulatan total</label>
            <SmartNativeSelect
              value={rounding}
              onChange={e => setRounding(e.target.value)}
              data-testid="mrp-rounding"
              className="w-40" wrapperClassName="w-40"
            >
              <option value="none">Tidak dibulatkan</option>
              <option value="ceil">Dibulatkan ke atas</option>
              <option value="floor">Dibulatkan ke bawah</option>
            </SmartNativeSelect>
          </div>
          <div className="flex items-center gap-2 pb-1.5">
            <Switch checked={includeStock} onCheckedChange={setIncludeStock} data-testid="mrp-include-stock" />
            <span className="text-sm text-foreground/70">Sertakan stok &amp; kekurangan</span>
          </div>
          <div className="ml-auto">
            <Button onClick={compute} disabled={loading} data-testid="mrp-compute-button">
              {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Calculator className="w-4 h-4 mr-2" />}
              {loading ? 'Menghitung…' : 'Hitung Kebutuhan'}
            </Button>
          </div>
        </div>
      </GlassPanel>

      {/* Results */}
      {result && (
        <div className="space-y-4" data-testid="mrp-result">
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            <SummaryCard label="Total Produksi" value={`${fmt(t.grand_qty_pcs, 0)} pcs`} icon={Layers} />
            <SummaryCard label="Jenis Material" value={t.total_material_lines} icon={PackageSearch} />
            <SummaryCard label="Total Bahan (kg)" value={`${fmt(readNumber(t, FIELD.totalMaterialKg))} kg`} icon={Layers} />
            <SummaryCard
              label="Material Kurang"
              value={t.total_shortfall_lines}
              icon={t.total_shortfall_lines > 0 ? AlertTriangle : CheckCircle2}
              tone={t.total_shortfall_lines > 0 ? 'danger' : 'success'}
            />
            {result.include_cost && (
              <SummaryCard label="Estimasi Biaya Material" value={rp(t.grand_total_cost)} icon={Wallet} highlight />
            )}
          </div>

          {(result.warnings || []).length > 0 && (
            <div className="rounded-lg border border-[hsl(var(--warning)/0.3)] bg-[hsl(var(--warning)/0.1)] p-3 text-sm text-[hsl(var(--warning))]"
                 data-testid="mrp-warnings">
              {result.warnings.map((w, i) => <div key={i}>• {w}</div>)}
            </div>
          )}

          {/* Aggregated table */}
          <GlassPanel className="p-0 overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-[var(--glass-border)]">
              <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <PackageSearch className="w-4 h-4 text-primary" /> Kebutuhan Material (Agregat)
              </h3>
              <Button variant="outline" size="sm" onClick={exportCSV}
                      disabled={agg.length === 0} data-testid="mrp-export-csv">
                <Download className="w-4 h-4 mr-2" /> Unduh CSV
              </Button>
            </div>
            {agg.length === 0 ? (
              <div className="text-center py-10 text-sm text-muted-foreground">
                Tidak ada material terhitung. Pastikan model/ukuran punya BOM aktif.
              </div>
            ) : (
              <Table data-testid="mrp-aggregated-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Kode</TableHead>
                    <TableHead>Nama Material</TableHead>
                    <TableHead>Kategori</TableHead>
                    <TableHead className="text-right">Total Kebutuhan</TableHead>
                    <TableHead>Unit</TableHead>
                    {/* 2026-11-06 (Tahap 2): per PO — yang sudah keluar dikurangkan; kekurangan dari sisa kebutuhan */}
                    {result.source === 'po' && <TableHead className="text-right">Sudah keluar</TableHead>}
                    {result.source === 'po' && <TableHead className="text-right">Sisa kebutuhan</TableHead>}
                    {result.include_cost && <TableHead className="text-right">Harga Satuan</TableHead>}
                    {result.include_cost && <TableHead className="text-right">Subtotal</TableHead>}
                    {result.include_stock && <TableHead className="text-right">On-hand</TableHead>}
                    {result.include_stock && <TableHead className="text-right">Tersedia</TableHead>}
                    {result.include_stock && <TableHead className="text-right">Kekurangan</TableHead>}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {agg.map((m, idx) => (
                    <TableRow key={idx} data-testid={`mrp-row-${idx}`}>
                      <TableCell className="tabular-nums text-xs">{m.code || '—'}</TableCell>
                      <TableCell className="font-medium">{m.name}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {m.category_name || m.material_type || '—'}
                        {m.is_kglike && <Badge variant="secondary" className="ml-1.5 text-[10px]">kain/benang</Badge>}
                      </TableCell>
                      <TableCell className="text-right tabular-nums font-semibold">{fmt(m.total_required)}</TableCell>
                      <TableCell className="text-xs">{m.unit}</TableCell>
                      {result.source === 'po' && (
                        <TableCell className="text-right tabular-nums text-xs" data-testid={`mrp-issued-${idx}`}>{fmt(m.issued)}</TableCell>
                      )}
                      {result.source === 'po' && (
                        <TableCell className="text-right tabular-nums text-xs font-semibold" data-testid={`mrp-remaining-${idx}`}>{fmt(m.remaining_required)}</TableCell>
                      )}
                      {result.include_cost && (
                        <TableCell className="text-right tabular-nums text-xs" data-testid={`mrp-unitcost-${idx}`}>
                          {rp(m.unit_cost)}
                          {m.cost_source === 'default' && (
                            <span className="ml-1 text-[hsl(var(--warning))]" title="Harga default costing-settings (material belum punya unit_cost)">*</span>
                          )}
                        </TableCell>
                      )}
                      {result.include_cost && (
                        <TableCell className="text-right tabular-nums text-xs font-semibold" data-testid={`mrp-subtotal-${idx}`}>
                          {rp(m.subtotal_cost)}
                        </TableCell>
                      )}
                      {result.include_stock && (
                        <TableCell className="text-right tabular-nums text-xs">
                          {m.material_id ? fmt(m.onhand) : <span className="text-muted-foreground">—</span>}
                        </TableCell>
                      )}
                      {result.include_stock && (
                        <TableCell className="text-right tabular-nums text-xs">
                          {m.material_id ? fmt(m.available) : <span className="text-muted-foreground">—</span>}
                        </TableCell>
                      )}
                      {result.include_stock && (
                        <TableCell className="text-right tabular-nums text-xs font-semibold">
                          {!m.material_id ? (
                            <span className="text-muted-foreground" title="Material belum tertaut ke master stok">n/a</span>
                          ) : m.shortfall > 0 ? (
                            <span className="text-[hsl(var(--destructive))]" data-testid={`mrp-shortfall-${idx}`}>{fmt(m.shortfall)}</span>
                          ) : (
                            <span className="text-[hsl(var(--success))]">0</span>
                          )}
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </GlassPanel>

          {/* Lines without BOM */}
          {noBom.length > 0 && (
            <GlassPanel className="p-4" data-testid="mrp-no-bom">
              <h4 className="text-sm font-semibold text-[hsl(var(--warning))] flex items-center gap-2 mb-2">
                <AlertTriangle className="w-4 h-4" /> Baris tanpa BOM aktif ({noBom.length})
              </h4>
              <div className="space-y-1 text-xs text-foreground/70">
                {noBom.map((l, i) => (
                  <div key={i}>
                    • {(l.model_code || l.model_id || '?')} · ukuran {(l.size_code || l.size_id || '?')} ·
                    {' '}{fmt(l.qty_pcs, 0)} pcs — <span className="text-[hsl(var(--warning)/0.8)]">{l.reason}</span>
                  </div>
                ))}
              </div>
            </GlassPanel>
          )}

          {/* Per-line breakdown */}
          {resolved.length > 0 && (
            <GlassPanel className="p-0 overflow-hidden">
              <button
                type="button"
                onClick={() => setShowBreakdown(v => !v)}
                className="w-full flex items-center justify-between p-4 text-sm font-semibold text-foreground hover:bg-foreground/5"
                data-testid="mrp-breakdown-toggle"
              >
                <span className="flex items-center gap-2">
                  {showBreakdown ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                  Rincian per baris ({resolved.length})
                </span>
              </button>
              {showBreakdown && (
                <Table data-testid="mrp-breakdown-table">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Model</TableHead>
                      <TableHead>Ukuran</TableHead>
                      <TableHead className="text-right">Qty</TableHead>
                      <TableHead className="text-right">Versi BOM</TableHead>
                      <TableHead className="text-right"># Material</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {resolved.map((l, i) => (
                      <TableRow key={i}>
                        <TableCell className="text-sm">{l.model_code || l.model_id}{l.label ? ` · ${l.label}` : ''}</TableCell>
                        <TableCell className="text-xs">{l.size_code || l.size_id}</TableCell>
                        <TableCell className="text-right tabular-nums">{fmt(l.qty_pcs, 0)}</TableCell>
                        <TableCell className="text-right tabular-nums text-xs">v{l.version}</TableCell>
                        <TableCell className="text-right tabular-nums text-xs">{l.material_count}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </GlassPanel>
          )}
        </div>
      )}
    </div>
  );
}

function SummaryCard({ label, value, icon: Icon, tone, highlight }) {
  const toneCls = tone === 'danger'
    ? 'text-[hsl(var(--destructive))]'
    : tone === 'success'
      ? 'text-[hsl(var(--success))]'
      : highlight
        ? 'text-primary'
        : 'text-foreground';
  return (
    <GlassPanel className={`p-4 ${highlight ? 'border-primary/40 bg-primary/5' : ''}`}>
      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
        {Icon && <Icon className={`w-4 h-4 ${toneCls}`} />} {label}
      </div>
      <div className={`text-2xl font-bold tabular-nums ${toneCls}`}>{value}</div>
    </GlassPanel>
  );
}

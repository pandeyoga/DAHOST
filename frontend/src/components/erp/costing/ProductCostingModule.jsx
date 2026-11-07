/**
 * ProductCostingModule — layar **HPP per Potong & per Model**.
 *
 * MENGAPA LAYAR INI ADA (fakta terukur 2026-08-23)
 * ------------------------------------------------
 * Sejak sesi #30 harga bahan lahir dari PEMBELIAN (rata-rata bergerak). Tetapi
 * HPP produk jadi belum pernah lahir dari angka itu: 321 dokumen FG semuanya
 * `hpp: 0` / `hpp_source: 'none'`, dan satu-satunya sumber HPP model adalah
 * kalkulator R&D atau KETIKAN manual (`base_hpp`). Akibatnya kolom margin di
 * Katalog Marketing selalu 0 dan pemilik tidak bisa tahu margin sebelum harga
 * jual ditetapkan.
 *
 * Di layar ini HPP/pcs dihitung dari data yang sudah ada:
 *   bahan (BOM × harga pembelian, sadar satuan) + upah CMT
 * 2026-11-06 (Tahap 2, keputusan owner): upah cutting/internal dan overhead TIDAK masuk HPP —
 * keduanya tetap beban bulanan; upah internal ditampilkan sebagai informasi "tidak masuk HPP".
 * lalu bisa DITERAPKAN ke master produk, FG per ukuran, dan item katalog.
 *
 * Aturan jujur: setiap angka menyebut ASALNYA, dan setiap kekurangan tampil
 * sebagai daftar yang bisa diklik menuju layar perbaikannya — tidak ada angka 0
 * yang diam-diam dianggap benar.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import FilterChips from '@/components/ui/filter-chips';
import {
  RefreshCw, Search, Wand2, AlertTriangle, CheckCircle2, Settings2,
  Loader2, ArrowRight, History, Lock, Info, TrendingUp, Layers, Calculator,
} from 'lucide-react';
import { toast } from 'sonner';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import Modal from '../Modal';
import { StatusBadge, EmptyState } from '../moduleAtoms';
import PageLayout, { DetailPanel } from '../layout/PageLayout';
import { MoneyInput } from '@/components/ui/money-input';
import { formatDateTimeID } from '@/lib/format';
import { categoryLabel } from '@/lib/itemTaxonomy';
import {
  costingApi, fmtRp, fmtNum, fmtPct, SOURCE_LABEL, COST_SOURCE_LABEL,
  STATUS_META, GAP_LABEL,
} from './costingApi';

const inputCls =
  'w-full h-9 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary)/0.35)]';

// 2026-11-05 (PANDUAN_UI G8): nada warna memakai token lewat StatusBadge — label tetap dari costingApi
// (dulu kelas warna palet langsung).
const SOURCE_TONE = {
  owner: 'primary', cmt_job_actual: 'success', wip_actual: 'success',
  settings_process_rates: 'info', settings_fallback: 'warning', none: 'danger',
};
const STATUS_TONE = { ready: 'success', partial: 'warning', no_bom: 'danger' };
const COST_SOURCE_TONE = {
  purchase: 'text-[hsl(var(--success))]', opening: 'text-[hsl(var(--info))]',
  master: 'text-[hsl(var(--warning))]', none: 'text-[hsl(var(--destructive))]',
};
// Asal HPP tersimpan (core/product_master.resolve_hpp) — dulu kode mentah "bom"/"rnd"/"manual".
const HPP_SOURCE_ID = { bom: 'dari BOM', rnd: 'dari R&D', manual: 'diketik manual', none: 'belum ada' };
const hppSource = (s) => HPP_SOURCE_ID[s] || (SOURCE_LABEL[s]?.text) || String(s || '—').replace(/_/g, ' ');
const posCls = (n) => (n >= 0 ? 'text-[hsl(var(--success))]' : 'text-[hsl(var(--destructive))]');

function SourcePill({ source, title }) {
  const m = SOURCE_LABEL[source] || SOURCE_LABEL.none;
  return (
    <span title={title || ''}>
      <StatusBadge tone={SOURCE_TONE[source] || 'danger'} label={m.text} className="normal-case tracking-normal" />
    </span>
  );
}

function StatusPill({ status }) {
  const m = STATUS_META[status] || STATUS_META.no_bom;
  return <StatusBadge tone={STATUS_TONE[status] || 'danger'} label={m.label} className="normal-case tracking-normal text-[11px]" />;
}

/**
 * 2026-11-05 (PANDUAN_UI G1/G3/G13): cetakan PageLayout — tombol halaman di kepala (di hub: baris tab),
 * pil status + cari + target margin di toolbar kiri, muat ulang di kanan; rincian per model dibuka DI HALAMAN
 * di atas tabel (dulu popup lebar). Setelan upah & margin tetap dialog (formulir isian).
 */
export default function ProductCostingModule({ token, onNavigate }) {
  const [rows, setRows] = useState([]);
  const [totals, setTotals] = useState(null);
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [onlyGaps, setOnlyGaps] = useState(false);
  const [targetMargin, setTargetMargin] = useState('');
  const [includeOverhead] = useState(false);   // Tahap 2: overhead tidak masuk HPP (saklar dihapus)
  const [detail, setDetail] = useState(null);         // hasil GET /models/{id}
  const [detailBusy, setDetailBusy] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [applyingAll, setApplyingAll] = useState(false);
  const [totalModels, setTotalModels] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({ limit: '300' });
      if (search.trim()) p.set('q', search.trim());
      if (onlyGaps) p.set('only_gaps', 'true');
      if (targetMargin !== '') p.set('target_margin_pct', String(targetMargin));
      p.set('include_overhead', includeOverhead ? '1' : '0');
      const d = await costingApi('GET', `/models?${p}`, token);
      setRows(d.items || []);
      setTotals(d.totals || null);
      setTotalModels(d.total_models ?? null);
      setSettings(d.settings || null);
      if (targetMargin === '' && d.settings) setTargetMargin(String(d.settings.target_margin_pct ?? 30));
    } catch (e) {
      toast.error(`Gagal memuat HPP produk: ${e.message}`);
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, search, onlyGaps, includeOverhead, targetMargin]);

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [onlyGaps, includeOverhead]);
  useEffect(() => {
    const t = setTimeout(() => load(), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, targetMargin]);

  const openDetail = async (modelId) => {
    setDetailBusy(true);
    try {
      const p = new URLSearchParams();
      if (targetMargin !== '') p.set('target_margin_pct', String(targetMargin));
      p.set('include_overhead', includeOverhead ? '1' : '0');
      const d = await costingApi('GET', `/models/${modelId}?${p}`, token);
      setDetail(d);
    } catch (e) {
      toast.error(`Gagal memuat rincian: ${e.message}`);
    } finally { setDetailBusy(false); }
  };
  const toggleDetail = (modelId) => (detail?.model?.id === modelId ? setDetail(null) : openDetail(modelId));

  const applyModel = async (modelId) => {
    try {
      const d = await costingApi('POST', `/models/${modelId}/apply`, token,
        { include_overhead: includeOverhead });
      toast.success(
        `HPP diterapkan: ${d.applied.length} ukuran @${fmtRp(d.hpp_model)} · ` +
        `${d.fg_updated} produk jadi & ${d.catalog_items_updated} item katalog ikut diperbarui.`);
      await load();
      if (detail?.model?.id === modelId) await openDetail(modelId);
    } catch (e) {
      toast.error(`Gagal menerapkan HPP: ${e.message}`);
    }
  };

  const applyAll = async () => {
    setApplyingAll(true);
    try {
      const d = await costingApi('POST', '/apply-all', token, { include_overhead: includeOverhead });
      toast.success(
        `${d.applied_count} produk diterapkan · ${d.fg_updated} produk jadi & ` +
        `${d.catalog_items_updated} item katalog diperbarui` +
        (d.skipped_count ? ` · ${d.skipped_count} dilewati (belum bisa dihitung)` : ''));
      await load();
    } catch (e) {
      toast.error(`Gagal menerapkan: ${e.message}`);
    } finally { setApplyingAll(false); }
  };

  const goto = (target) => {
    if (!target || target === 'fin-hpp-produk') return;
    if (typeof onNavigate === 'function') { onNavigate(target); return; }
    window.location.hash = target;
    window.location.reload();
  };

  const stat = (k) => (totals ? (totals[k] ?? 0) : 0);
  const readyCount = useMemo(() => rows.filter(r => r.status === 'ready').length, [rows]);
  // 2026-11-04 (audit Keuangan tahap 2): 4 kartu hitungan → tab status yang menyaring tabel
  const [statusTab, setStatusTab] = useState('');
  const shownRows = useMemo(() => (statusTab ? rows.filter(r => r.status === statusTab) : rows), [rows, statusTab]);
  const openId = detail?.model?.id;

  const filters = (
    <>
      <FilterChips value={statusTab} onChange={setStatusTab} testId="costing-summary" ariaLabel="Status HPP" hideWhenEmpty={false}
        options={[{ key: '', label: 'Semua', count: stat('models') }, { key: 'ready', label: 'Siap', count: stat('ready') },
          { key: 'partial', label: 'Masih ada kekurangan', count: stat('partial') }, { key: 'no_bom', label: 'Belum ada BOM', count: stat('no_bom') }]} />
      <div className="relative w-64 max-w-full">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <GlassInput value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Cari kode / nama produk…" className="pl-9 h-9"
          data-testid="costing-search" />
      </div>
      <label className="flex items-center gap-2 text-sm text-foreground/80 h-9 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)]">
        <span>Target margin</span>
        <input type="number" min="0" max="99" step="1" value={targetMargin}
          onChange={e => setTargetMargin(e.target.value)}
          className="w-12 bg-transparent text-right font-semibold text-foreground focus:outline-none"
          data-testid="costing-target-margin" />
        <span>%</span>
      </label>
      <label className="flex items-center gap-2 text-sm text-foreground/80 cursor-pointer">
        <input type="checkbox" checked={onlyGaps} onChange={e => setOnlyGaps(e.target.checked)}
          data-testid="costing-filter-gaps" />
        Hanya yang masih ada kekurangan
      </label>
    </>
  );

  return (
    <PageLayout
      testId="product-costing-page"
      title="HPP per potong & per model"
      subtitle="HPP/pcs = BOM × harga beli rata-rata + upah CMT. Upah internal dan overhead tidak masuk HPP."
      actions={<>
        <Button variant="outline" onClick={() => setShowSettings(true)} data-testid="costing-open-settings">
          <Settings2 className="w-4 h-4" />Setelan margin
        </Button>
        <Button onClick={applyAll} disabled={applyingAll || !readyCount} data-testid="costing-apply-all">
          {applyingAll ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
          Terapkan semua yang siap{readyCount ? ` (${readyCount})` : ''}
        </Button>
      </>}
      filters={filters}
      tools={
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={load} disabled={loading} data-testid="costing-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      }
      summary={<>
        {totalModels != null && totalModels > stat('models') && (
          <p className="text-sm text-[hsl(var(--warning))]" data-testid="costing-truncated">
            Dihitung {stat('models')} dari {totalModels} model (urut kode). Cari kode/nama untuk melihat model lainnya.
          </p>
        )}
        {/* penjelasan jujur bila belum ada yang siap */}
        {!loading && stat('ready') === 0 && (
          <div className="flex items-start gap-2 rounded-[var(--radius-md)] bg-[hsl(var(--warning)/0.08)] px-4 py-3 text-sm text-[hsl(var(--warning))]"
            data-testid="costing-empty-warning">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <p>
              <strong>Belum ada produk yang bisa dihitung penuh.</strong> Yang paling sering kurang:
              BOM per ukuran belum dibuat, ada bahan yang belum pernah dibeli (jadi belum punya
              harga), atau upah CMT/cutting belum dikunci. Buka <em>Rincian</em> pada baris mana pun
              untuk melihat daftar kekurangannya dan tombol perbaikannya.
            </p>
          </div>
        )}
        {detailBusy && !detail && (
          <p className="text-sm text-muted-foreground flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> Memuat rincian…
          </p>
        )}
      </>}
      detail={detail && (
        // key: isian upah milik model lain tidak boleh terbawa saat rincian model berikutnya dibuka
        <CostDetail key={detail.model?.id} detail={detail} token={token} onClose={() => setDetail(null)}
          onApply={() => applyModel(detail.model.id)}
          onReload={() => openDetail(detail.model.id)}
          onGoto={goto} />
      )}
    >
      {/* ── tabel ──────────────────────────────────────────────────────── */}
      <GlassCard className="p-0 overflow-hidden">
        {loading && rows.length === 0 ? (
          <div className="space-y-2 p-4">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : shownRows.length === 0 ? (
          <EmptyState icon={Calculator} title="Tidak ada produk pada penyaring ini"
            description="Ubah pencarian, pil status, atau hilangkan centang “Hanya yang masih ada kekurangan”." />
        ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="costing-table">
            <thead>
              <tr>
                <th className="text-left">Kode</th>
                <th className="text-left">Produk</th>
                <th className="text-center">Ukuran ber-BOM</th>
                <th className="text-right">Bahan/pcs</th>
                <th className="text-right">Upah CMT</th>
                <th className="text-right">Upah internal (tidak masuk HPP)</th>
                <th className="text-right">HPP/pcs</th>
                <th className="text-right">Harga jual</th>
                <th className="text-right">Margin</th>
                <th className="text-right">Usulan harga</th>
                <th className="text-left">Status</th>
                <th className="text-right">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {shownRows.map(r => (
                <tr key={r.model_id}
                  className={`border-t border-[var(--glass-border)] hover:bg-[var(--glass-bg-hover)] ${openId === r.model_id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}
                  data-testid={`costing-row-${r.code}`}>
                  <td className="text-xs text-muted-foreground whitespace-nowrap">{r.code}</td>
                  <td className="text-foreground">
                    {r.name}
                    <span className="block text-[10px] text-muted-foreground">
                      {r.category_name || 'tanpa kategori'}
                      {r.hpp_bom_current > 0 && (
                        <span className="text-[hsl(var(--success))]">
                          {' '}· tersimpan {fmtRp(r.hpp_bom_current)}
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="text-center text-xs text-foreground whitespace-nowrap tabular-nums">
                    {r.sizes_with_bom}/{r.size_count}
                  </td>
                  <td className="text-right tabular-nums text-foreground whitespace-nowrap">
                    {r.material_cost_avg > 0 ? fmtRp(r.material_cost_avg) : '—'}
                  </td>
                  <td className="text-right whitespace-nowrap">
                    <span className="tabular-nums text-foreground">
                      {r.cmt_cost > 0 ? fmtRp(r.cmt_cost) : '—'}
                    </span>
                    <span className="block mt-0.5"><SourcePill source={r.cmt_source} /></span>
                  </td>
                  <td className="text-right whitespace-nowrap">
                    <span className="tabular-nums text-foreground">
                      {r.internal_labor_cost > 0 ? fmtRp(r.internal_labor_cost) : '—'}
                    </span>
                    <span className="block mt-0.5"><SourcePill source={r.internal_labor_source} /></span>
                  </td>
                  <td className="text-right tabular-nums font-bold text-foreground whitespace-nowrap"
                    data-testid={`costing-hpp-${r.code}`}>
                    {r.hpp_avg > 0 ? fmtRp(r.hpp_avg) : '—'}
                    {r.hpp_min > 0 && r.hpp_max > r.hpp_min && (
                      <span className="block text-[10px] font-normal text-muted-foreground">
                        {fmtRp(r.hpp_min)}–{fmtRp(r.hpp_max)} per ukuran
                      </span>
                    )}
                  </td>
                  <td className="text-right tabular-nums text-foreground whitespace-nowrap">
                    {r.price_best > 0 ? fmtRp(r.price_best)
                      : <span className="text-muted-foreground">belum ada</span>}
                  </td>
                  <td className="text-right tabular-nums whitespace-nowrap"
                    data-testid={`costing-margin-${r.code}`}>
                    {r.margin_known ? (
                      <span className={posCls(r.margin_pct)}>
                        {fmtPct(r.margin_pct)}
                      </span>
                    ) : (
                      /* SESI #32 (temuan penguji): dulu sel ini hanya bertanda "—"
                         sehingga alasannya hanya terbaca kalau kursor didiamkan di
                         atasnya. Sekarang alasannya DITULIS. */
                      <span className="text-[10px] text-muted-foreground" title={r.price_best > 0
                        ? 'HPP belum bisa dihitung — margin tidak ditampilkan supaya tidak menyesatkan'
                        : 'Margin baru bisa dihitung setelah harga jual ditetapkan'}>
                        {r.price_best > 0 ? 'HPP belum ada' : 'harga jual belum ada'}
                      </span>
                    )}
                  </td>
                  <td className="text-right tabular-nums text-[hsl(var(--primary))] whitespace-nowrap">
                    {r.suggested_price > 0 ? fmtRp(r.suggested_price) : '—'}
                  </td>
                  <td className="whitespace-nowrap">
                    <StatusPill status={r.status} />
                    {r.gap_count > 0 && (
                      <span className="block text-[10px] text-[hsl(var(--warning))] mt-0.5">
                        {r.gap_count} kekurangan
                      </span>
                    )}
                  </td>
                  <td className="text-right whitespace-nowrap">
                    <span className="inline-flex items-center gap-2">
                      <Button variant="link" size="sm" className="h-auto p-0" onClick={() => toggleDetail(r.model_id)}
                        data-testid={`costing-detail-${r.code}`}>{openId === r.model_id ? 'Tutup' : 'Rincian'}</Button>
                      <Button variant="outline" size="sm" onClick={() => applyModel(r.model_id)}
                        disabled={r.sizes_with_bom === 0}
                        data-testid={`costing-apply-${r.code}`}>Terapkan</Button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        )}
      </GlassCard>

      {showSettings && (
        <CostingSettingsModal token={token} onClose={() => setShowSettings(false)}
          onSaved={() => { setShowSettings(false); load(); }} />
      )}
    </PageLayout>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   RINCIAN PER MODEL — baris BOM, upah, kekurangan, riwayat penerapan.
   2026-11-05 (PANDUAN_UI G13): dibuka DI HALAMAN (DetailPanel) di atas tabel — dulu popup lebar.
   Di dalam panel tidak ada kartu lagi (kartu di dalam kartu); bagian dipisah garis tipis.
   ═══════════════════════════════════════════════════════════════════════ */
function CostDetail({ detail, token, onClose, onApply, onReload, onGoto }) {
  const m = detail.model || {};
  const [cmt, setCmt] = useState(detail.override?.cmt_rate_per_pcs ?? '');
  const [internal, setInternal] = useState(detail.override?.internal_labor_per_pcs ?? '');
  const [saving, setSaving] = useState(false);
  const [snapshots, setSnapshots] = useState(null);

  const saveLabor = async () => {
    setSaving(true);
    try {
      await costingApi('PUT', `/models/${m.id}/labor`, token, {
        cmt_rate_per_pcs: cmt === '' ? null : Number(cmt),
        internal_labor_per_pcs: internal === '' ? null : Number(internal),
      });
      toast.success('Upah dikunci — HPP dihitung ulang.');
      await onReload();
    } catch (e) {
      toast.error(`Gagal menyimpan upah: ${e.message}`);
    } finally { setSaving(false); }
  };

  const loadSnapshots = async () => {
    try {
      const d = await costingApi('GET', `/snapshots?model_id=${m.id}&limit=20`, token);
      setSnapshots(d.items || []);
    } catch (e) {
      toast.error(`Gagal memuat riwayat: ${e.message}`);
    }
  };

  /** Salin BOM ukuran yang sudah ada ke ukuran lain (endpoint master BOM). */
  const onCopyBom = async (g) => {
    try {
      const res = await fetch(
        `${process.env.REACT_APP_BACKEND_URL || ''}/api/rahaza/boms/${g.copy_bom_id}/copy-to-sizes`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token || localStorage.getItem('erp_token')}`,
          },
          body: JSON.stringify({ target_size_ids: g.target_size_ids || [] }),
        });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      toast.success(
        `BOM disalin ke ${(d.created || []).length} ukuran dari ukuran ${g.copy_from_size} — ` +
        'periksa & sesuaikan pemakaian tiap ukuran bila perlu.');
      await onReload();
    } catch (e) {
      toast.error(`Gagal menyalin BOM: ${e.message}`);
    }
  };

  const section = 'border-t border-[var(--glass-border)] pt-3';
  const heading = 'text-sm font-semibold text-foreground flex items-center gap-1.5';

  return (
    <DetailPanel title={`HPP — ${m.code} · ${m.name}`} onClose={onClose} testId="costing-detail-modal"
      description={`HPP rata-rata ${fmtRp(detail.hpp_model_avg)}/pcs · usulan harga jual ${fmtRp(detail.suggested_price_model)} (target margin ${fmtPct(detail.target_margin_pct)})`}
      actions={<>
        <Button onClick={saveLabor} disabled={saving} data-testid="costing-save-labor">
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Lock className="w-4 h-4" />}
          Kunci upah
        </Button>
        <Button variant="outline" onClick={onApply} data-testid="costing-detail-apply">
          <CheckCircle2 className="w-4 h-4" />Hitung &amp; terapkan
        </Button>
      </>}>
      <div className="space-y-4">
        {/* upah + ringkasan */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="space-y-2">
            <p className={heading}><Lock className="w-3.5 h-3.5 text-[hsl(var(--primary))]" /> Upah CMT / jahit per pcs</p>
            <MoneyInput unstyled value={cmt}
              onChange={e => setCmt(e.target.value)} placeholder="kosong = ikut data nyata"
              className={inputCls} data-testid="costing-input-cmt" />
            <div className="text-xs text-muted-foreground">
              Berlaku: <strong className="text-foreground">{fmtRp(detail.cmt.rate)}</strong>{' '}
              <SourcePill source={detail.cmt.source} /> {detail.cmt.note}
            </div>
            {(detail.cmt.candidates || []).length > 0 && (
              <div className="flex flex-wrap gap-1.5" data-testid="costing-cmt-candidates">
                {detail.cmt.candidates.slice(0, 6).map((c, i) => (
                  <Button key={i} variant="outline" size="sm" onClick={() => setCmt(String(c.rate))}
                    title={`${c.label} — ${c.detail}`} className="text-xs">
                    {fmtRp(c.rate)} · {c.label.slice(0, 22)}
                  </Button>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <p className={heading}><Lock className="w-3.5 h-3.5 text-[hsl(var(--primary))]" /> Upah cutting / internal per pcs — tidak masuk HPP</p>
            <MoneyInput unstyled value={internal}
              onChange={e => setInternal(e.target.value)} placeholder="kosong = ikut data produksi"
              className={inputCls} data-testid="costing-input-internal" />
            <div className="text-xs text-muted-foreground">
              Berlaku: <strong className="text-foreground">{fmtRp(detail.internal_labor.rate)}</strong>{' '}
              <SourcePill source={detail.internal_labor.source} /> {detail.internal_labor.note}
            </div>
            {(detail.internal_labor.processes || []).length > 0 && (
              <div className="text-xs text-muted-foreground">
                {detail.internal_labor.processes.map(p =>
                  `${p.process_code} ${fmtRp(p.rate_per_pcs)}`).join(' + ')}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <p className={heading}><TrendingUp className="w-3.5 h-3.5 text-[hsl(var(--primary))]" /> Ringkasan</p>
            <div className="text-sm text-muted-foreground space-y-1">
              <div>HPP rata-rata: <strong className="text-foreground tabular-nums">{fmtRp(detail.hpp_model_avg)}</strong>/pcs</div>
              <div>Target margin {fmtPct(detail.target_margin_pct)} ⇒ usulan harga jual{' '}
                <strong className="text-[hsl(var(--primary))] tabular-nums">{fmtRp(detail.suggested_price_model)}</strong></div>
              <div>Upah internal dan overhead: tidak masuk HPP (beban bulanan)</div>
              <div>HPP tersimpan sekarang: {fmtRp(m.hpp_current)}{' '}
                <span className="text-xs">({hppSource(m.hpp_source_current)})</span></div>
            </div>
          </div>
        </div>

        {/* kekurangan */}
        {(detail.gaps || []).length > 0 && (
          <div className={section} data-testid="costing-gaps">
            <p className="text-sm font-semibold text-[hsl(var(--warning))] flex items-center gap-1.5 mb-2">
              <AlertTriangle className="w-3.5 h-3.5" /> {detail.gaps.length} kekurangan yang menahan HPP
            </p>
            <ul className="space-y-1.5">
              {detail.gaps.map((g, i) => (
                <li key={i} className="flex items-start justify-between gap-3 text-sm"
                  data-testid={`costing-gap-${g.code}`}>
                  <div className="text-foreground/90">
                    <span className="font-semibold">{GAP_LABEL[g.code] || g.code}</span>
                    <span className="block text-xs text-muted-foreground">{g.message}</span>
                  </div>
                  {g.code === 'bom_missing_other_sizes' && g.copy_bom_id ? (
                    <Button variant="link" size="sm" className="h-auto p-0 shrink-0" onClick={() => onCopyBom(g)}
                      data-testid="costing-copy-bom">
                      Salin BOM ke {(g.target_size_ids || []).length} ukuran <ArrowRight className="w-3 h-3" />
                    </Button>
                  ) : g.target && g.target !== 'fin-hpp-produk' ? (
                    <Button variant="link" size="sm" className="h-auto p-0 shrink-0" onClick={() => onGoto(g.target)}
                      data-testid={`costing-fix-${g.code}`}>
                      {g.action || 'Perbaiki'} <ArrowRight className="w-3 h-3" />
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* per ukuran */}
        {(detail.sizes || []).map(s => (
          <div key={s.size_id} className={section} data-testid={`costing-size-${s.size_code || s.size_id}`}>
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <p className="text-sm font-semibold text-foreground flex items-center gap-2">
                <Layers className="w-4 h-4 text-[hsl(var(--primary))]" /> Ukuran {s.size_code || '—'}
                {s.bom_id ? (
                  <span className="text-xs text-muted-foreground font-normal">
                    BOM v{s.bom_version} · {s.line_count} baris bahan
                  </span>
                ) : (
                  <span className="text-xs text-[hsl(var(--destructive))] font-normal">BOM belum ada</span>
                )}
              </p>
              <div className="text-sm text-foreground flex items-center gap-3 flex-wrap tabular-nums">
                {s.bom_id ? (
                  <>
                    <span>Bahan <strong>{fmtRp(s.material_cost)}</strong></span>
                    <span>CMT <strong>{fmtRp(s.cmt_cost)}</strong></span>
                    <span className="text-muted-foreground">Upah internal {fmtRp(s.internal_labor_cost)} (tidak masuk HPP)</span>
                    <span className="text-[hsl(var(--primary))]">HPP <strong>{fmtRp(s.hpp_unit)}</strong>/pcs</span>
                    <span>Usulan jual <strong>{fmtRp(s.suggested_price)}</strong></span>
                    {s.margin_known
                      ? <span className={posCls(s.margin_pct)}>
                          Margin <strong>{fmtRp(s.margin)}</strong> ({fmtPct(s.margin_pct)})
                        </span>
                      : <span className="text-muted-foreground">
                          {s.has_price ? 'margin belum bisa dihitung (HPP belum lengkap)'
                            : 'harga jual belum ada'}
                        </span>}
                  </>
                ) : (
                  <span className="text-muted-foreground">
                    Belum bisa dihitung — buat BOM untuk ukuran ini dulu.
                  </span>
                )}
              </div>
            </div>

            {s.lines?.length > 0 && (
              <div className="overflow-x-auto mt-2">
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      <th className="text-left">Bahan</th>
                      <th className="text-left">Jenis</th>
                      <th className="text-right">Pakai (BOM)</th>
                      <th className="text-right">Satuan dasar</th>
                      <th className="text-right">Harga satuan</th>
                      <th className="text-right">Biaya/pcs</th>
                      <th className="text-left">Catatan</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.lines.map((ln, i) => {
                      const cs = COST_SOURCE_LABEL[ln.cost_source] || COST_SOURCE_LABEL.none;
                      return (
                        <tr key={i} className="border-b border-[var(--glass-border)]/50">
                          <td className="text-foreground">
                            <span className="text-[10px] text-muted-foreground">{ln.code}</span>
                            <span className="block">{ln.name}</span>
                          </td>
                          <td className="text-muted-foreground">{ln.material_type ? categoryLabel(ln.material_type) : '—'}</td>
                          <td className="text-right tabular-nums whitespace-nowrap text-foreground">
                            {fmtNum(ln.qty_input, 4)} {ln.unit_input}
                          </td>
                          <td className="text-right tabular-nums whitespace-nowrap text-foreground">
                            {fmtNum(ln.qty_base, 4)} {ln.unit_base}
                          </td>
                          <td className="text-right tabular-nums whitespace-nowrap text-foreground">
                            {ln.unit_cost > 0 ? fmtRp(ln.unit_cost) : '—'}
                            <span className={`block text-[10px] ${COST_SOURCE_TONE[ln.cost_source] || COST_SOURCE_TONE.none}`}>{cs.text}</span>
                          </td>
                          <td className="text-right tabular-nums whitespace-nowrap font-semibold text-foreground">
                            {fmtRp(ln.amount)}
                          </td>
                          <td className="text-muted-foreground">
                            {ln.status === 'unvalued' && (
                              <span className="text-[hsl(var(--destructive))]">belum punya harga — belum pernah dibeli</span>)}
                            {ln.status === 'unlinked' && (
                              <span className="text-[hsl(var(--destructive))]">belum tertaut master bahan</span>)}
                            {ln.status === 'uom_unclear' && (
                              <span className="text-[hsl(var(--warning))]">{ln.uom_note || 'satuan belum jelas'}</span>)}
                            {ln.status === 'ok' && <span className="text-xs">{ln.notes || ''}</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {s.fg_variants?.length > 0 && s.bom_id && (
              <div className="mt-2 text-xs text-muted-foreground">
                Produk jadi yang ikut diperbarui ({s.fg_variants.length}):{' '}
                {s.fg_variants.slice(0, 6).map(v => (
                  <span key={v.id} className="mr-2">
                    <span className="text-foreground">{v.code}</span>
                    {v.hpp_current > 0 && (
                      <span className="text-[hsl(var(--success))]">
                        {' '}(HPP {fmtRp(v.hpp_current)} · {hppSource(v.hpp_source_current)})
                      </span>
                    )}
                  </span>
                ))}
                {s.fg_variants.length > 6 && (
                  <span>+{s.fg_variants.length - 6} varian lain</span>
                )}
              </div>
            )}
          </div>
        ))}

        {/* riwayat penerapan */}
        <div className={section}>
          {snapshots === null ? (
            <Button variant="link" size="sm" className="h-auto p-0" onClick={loadSnapshots} data-testid="costing-load-history">
              <History className="w-3.5 h-3.5" /> Lihat riwayat penerapan HPP
            </Button>
          ) : snapshots.length === 0 ? (
            <p className="text-sm text-muted-foreground flex items-center gap-1.5">
              <Info className="w-3.5 h-3.5" /> HPP produk ini belum pernah diterapkan.
            </p>
          ) : (
            <div data-testid="costing-history">
              <p className="text-sm font-semibold text-foreground mb-2">Riwayat penerapan HPP</p>
              <ul className="space-y-1 text-sm text-muted-foreground">
                {snapshots.map(s => (
                  <li key={s.id}>
                    <span className="text-foreground tabular-nums">{fmtRp(s.hpp_model)}</span>{' '}
                    · {(s.applied_sizes || []).length} ukuran · upah dari{' '}
                    {(SOURCE_LABEL[s.cmt_source]?.text) || s.cmt_source} / {(SOURCE_LABEL[s.internal_labor_source]?.text) || s.internal_labor_source}
                    {' '}· {formatDateTimeID(s.created_at)}
                    {s.created_by_name ? ` · oleh ${s.created_by_name}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </DetailPanel>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SETELAN — overhead (informasi), target margin, tarif cadangan
   Tahap 9 (7 Nov 2026): tarif standar per tahap pindah ke tab "Tarif standar" di menu HPP (dulu tabel di
   dialog ini + Master Proses) — satu tempat mengubah `process_rates`; dialog ini tidak mengirimnya lagi.
   ═══════════════════════════════════════════════════════════════════════ */
function CostingSettingsModal({ token, onClose, onSaved }) {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        setSettings(await costingApi('GET', '/settings', token));
      } catch (e) {
        toast.error(`Gagal memuat setelan: ${e.message}`);
      } finally { setLoading(false); }
    })();
  }, [token]);

  const save = async () => {
    setSaving(true);
    try {
      await costingApi('PUT', '/settings', token, {
        overhead_rate_per_pcs: Number(settings.overhead_rate_per_pcs || 0),
        target_margin_pct: Number(settings.target_margin_pct || 0),
        labor_rate_fallback_per_pcs: Number(settings.labor_rate_fallback_per_pcs || 0),
      });
      toast.success('Setelan margin & tarif cadangan disimpan.');
      onSaved();
    } catch (e) {
      toast.error(`Gagal menyimpan setelan: ${e.message}`);
    } finally { setSaving(false); }
  };

  return (
    <Modal title="Setelan margin & tarif cadangan" onClose={onClose} size="lg"
      data-testid="costing-settings-modal">
      {loading || !settings ? (
        <div className="py-8 text-center text-muted-foreground text-sm">Memuat…</div>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-muted-foreground" data-testid="costing-settings-rates-moved">
            Tarif standar per tahap diatur di tab Tarif standar (menu HPP). Proses jahit/CMT memakai upah di form PO.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <label className="block">
              <span className="text-xs font-medium text-foreground/80">Overhead per pcs (tidak masuk HPP)</span>
              <MoneyInput unstyled value={settings.overhead_rate_per_pcs}
                onChange={e => setSettings({ ...settings, overhead_rate_per_pcs: e.target.value })}
                className={`${inputCls} mt-1`} data-testid="costing-setting-overhead" />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-foreground/80">Target margin bawaan (%)</span>
              <input type="number" min="0" max="99" step="1" value={settings.target_margin_pct}
                onChange={e => setSettings({ ...settings, target_margin_pct: e.target.value })}
                className={`${inputCls} mt-1`} data-testid="costing-setting-margin" />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-foreground/80">Tarif cadangan upah/pcs</span>
              <MoneyInput unstyled value={settings.labor_rate_fallback_per_pcs}
                onChange={e => setSettings({ ...settings, labor_rate_fallback_per_pcs: e.target.value })}
                className={`${inputCls} mt-1`} data-testid="costing-setting-fallback" />
            </label>
          </div>

          <p className="text-sm text-muted-foreground" data-testid="costing-setting-include-overhead">
            Upah internal dan overhead pabrik tidak masuk HPP produk (keputusan pemilik 6 Nov 2026); keduanya tetap beban bulanan.
          </p>

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" onClick={onClose} data-testid="costing-settings-cancel">Batal</Button>
            <Button onClick={save} disabled={saving} data-testid="costing-settings-save">
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}Simpan setelan
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

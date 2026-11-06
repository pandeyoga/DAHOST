import { useState, useEffect, useCallback, useMemo } from 'react';
import { RefreshCw, Save, Package, BarChart3, Building2, Settings2, Download, FileSpreadsheet, Factory, Calculator } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile, StatusBadge, EmptyState } from './moduleAtoms';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import Modal from './Modal';
import { HppComparisonInline } from './HppComparisonInline';
import { toast } from 'sonner';
import { posToLegacyOrders } from '@/lib/maklonOrderAdapter';
import { formatRupiah } from '@/lib/format';
import { categoryLabel } from '@/lib/itemTaxonomy';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB } from '@/lib/waktu';
import { readNumber, FIELD } from '@/lib/materialFields';  // FASE 6.6-B

const fmt = formatRupiah;
const NO_DATA = 'belum ada data';
const pct =(n) => `${Number(n || 0).toLocaleString('id-ID', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;

// Status job produksi & order maklon dalam bahasa staf (dulu kode mentah: "In Progress", "in_production").
const STATUS_ID = {
  'in progress': { label: 'Sedang dikerjakan', tone: 'info' }, open: { label: 'Terbuka', tone: 'default' },
  pending: { label: 'Menunggu', tone: 'warning' }, draft: { label: 'Draf', tone: 'muted' },
  confirmed: { label: 'Dikonfirmasi', tone: 'info' }, released: { label: 'Dirilis', tone: 'info' },
  'in production': { label: 'Diproduksi', tone: 'info' }, cutting: { label: 'Cutting', tone: 'info' },
  packing: { label: 'Packing', tone: 'info' }, 'partial delivered': { label: 'Terkirim sebagian', tone: 'warning' },
  completed: { label: 'Selesai', tone: 'success' }, done: { label: 'Selesai', tone: 'success' },
  finished: { label: 'Selesai', tone: 'success' }, invoiced: { label: 'Sudah ditagih', tone: 'success' },
  closed: { label: 'Ditutup', tone: 'muted' }, 'closed short': { label: 'Ditutup (kurang)', tone: 'muted' },
  cancelled: { label: 'Dibatalkan', tone: 'muted' },
  canceled: { label: 'Dibatalkan', tone: 'muted' },
};
function JobStatus({ status }) {
  const key = String(status || '').toLowerCase().replace(/[_\s]+/g, ' ').trim();
  const m = STATUS_ID[key] || { label: key || '—', tone: 'default' };
  return <StatusBadge tone={m.tone} label={m.label} />;
}

const TABS = [
  { key: 'internal-wo', label: 'Work order internal', icon: Package },
  { key: 'maklon', label: 'Maklon', icon: BarChart3 },
  { key: 'client-analysis', label: 'Per klien', icon: Building2 },
  { key: 'po-wip', label: 'Sisa WIP per PO', icon: Calculator },
];

/**
 * HPP aktual (menu HPP › HPP aktual): job produksi internal, order maklon, dan analisa per klien.
 * 2026-11-05 (PANDUAN_UI G1/G4/G13): cetakan PageLayout; tiga tab Radix di dalam tab hub → pil penyaring di
 * toolbar; daftar job = tabel, rincian HPP job dibuka DI HALAMAN di atas tabel (dulu daftar tombol bergulir
 * 500 px + panel di sebelahnya); pengaturan biaya bawaan = formulir pendek di dialog (dulu kartu dengan
 * tombol "Simpan Settings" sendirian di satu baris); label Indonesia.
 */
export default function RahazaHPPModule({ token }) {
  const [activeTab, setActiveTab] = useState('internal-wo');
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const page = {
    testId: 'rahaza-hpp-page',
    title: 'HPP aktual',
    subtitle: 'HPP dari data nyata: bahan keluar + upah CMT. Upah internal dan overhead tidak masuk HPP.',
    chips: (
      <div className="contents" data-testid="hpp-tabs">
        <FilterChips value={activeTab} onChange={setActiveTab} testId="hpp-actual-tab" ariaLabel="Jenis HPP" hideWhenEmpty={false} options={TABS} />
      </div>
    ),
  };

  if (activeTab === 'maklon') return <MaklonActualTab token={token} headers={headers} page={page} />;
  if (activeTab === 'client-analysis') return <ClientAnalysisTab token={token} headers={headers} page={page} />;
  if (activeTab === 'po-wip') return <PoWipTab headers={headers} page={page} />;
  return <InternalWOTab token={token} headers={headers} page={page} />;
}

/** Tabel rincian kecil di dalam panel/kartu (bahan atau upah). */
function BreakdownTable({ columns, rows, testId }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid={testId}>
        <thead>
          <tr>{columns.map((c) => <th key={c.key} className={c.right ? 'text-right' : 'text-left'}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-[var(--glass-border)]">
              {columns.map((c) => (
                <td key={c.key} className={c.right ? 'text-right tabular-nums whitespace-nowrap' : (c.muted ? 'text-muted-foreground' : '')}>{c.render(r)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const MATERIAL_COLS = [
  { key: 'name', label: 'Bahan', render: (m) => m.material_name },
  { key: 'type', label: 'Jenis', muted: true, render: (m) => (m.type ? categoryLabel(m.type) : '—') },
  { key: 'qty', label: 'Qty', right: true, render: (m) => `${Number(m.qty || 0).toLocaleString('id-ID')} ${m.unit || ''}` },
  { key: 'unit_cost', label: 'Harga satuan', right: true, render: (m) => fmt(m.unit_cost) },
  { key: 'source', label: 'Asal harga', muted: true, render: (m) => m.cost_source_label || '—' },
  { key: 'amount', label: 'Jumlah', right: true, render: (m) => fmt(m.amount) },
];
const CMT_COLS = [
  { key: 'sku', label: 'SKU', render: (c) => c.sku || '—' },
  { key: 'qty', label: 'Qty jadi', right: true, render: (c) => `${Number(c.qty || 0).toLocaleString('id-ID')} pcs` },
  { key: 'rate', label: 'Tarif jahit SPK', right: true, render: (c) => (c.rate > 0 ? fmt(c.rate) : 'belum diisi') },
  { key: 'amount', label: 'Jumlah', right: true, render: (c) => fmt(c.amount) },
];
const LABOR_COLS = [
  { key: 'op', label: 'Operator', render: (l) => l.operator_name || '—' },
  { key: 'proc', label: 'Proses', muted: true, render: (l) => l.process_code || '—' },
  { key: 'qty', label: 'Qty', right: true, render: (l) => `${Number(l.qty || 0).toLocaleString('id-ID')} pcs` },
  { key: 'rate', label: 'Tarif', right: true, render: (l) => fmt(l.rate) },
  { key: 'amount', label: 'Jumlah', right: true, render: (l) => fmt(l.amount) },
];

/** Angka ringkas tanpa kartu (dipakai di dalam panel — kartu di dalam kartu tidak dipakai). */
function Figure({ label, value, testId, strong }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${strong ? 'text-[hsl(var(--primary))]' : 'text-foreground'}`} data-testid={testId}>{value}</p>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1: Work order internal
// ══════════════════════════════════════════════════════════════════════════════
function InternalWOTab({ headers, page }) {
  const [settings, setSettings] = useState(null);
  const [draft, setDraft] = useState(null);           // salinan pengaturan yang sedang diubah di dialog
  const [wos, setWos] = useState([]);
  const [selected, setSelected] = useState(null);
  const [hpp, setHpp] = useState(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [loading, setLoading] = useState(true);
  const { page: pg, setPage, totalPages, paged } = useClientPagination(wos, 25);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [cs, ws] = await Promise.all([
        fetch('/api/rahaza/costing-settings', { headers }).then(r => r.json()),
        // FASE 5: HPP internal kini per JOB (engine baru)
        fetch('/api/production-jobs?business_type=internal', { headers }).then(r => r.json()),
      ]);
      setSettings(cs || null);
      setWos(Array.isArray(ws) ? ws : []);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const computeHPP = async (wo_id) => {
    const r = await fetch(`/api/production-jobs/${wo_id}/hpp`, { headers });
    if (r.ok) setHpp(await r.json());
    else { toast.error(`Gagal menghitung HPP job (HTTP ${r.status})`); setSelected(null); }
  };
  const openJob = (w) => {
    if (selected?.id === w.id) { setSelected(null); setHpp(null); return; }
    setSelected(w); setHpp(null);
    computeHPP(w.id);
  };

  const saveSettings = async () => {
    setSavingSettings(true);
    try {
      const r = await fetch('/api/rahaza/costing-settings', { method: 'PUT', headers, body: JSON.stringify(draft) });
      if (!r.ok) { toast.error(`Gagal menyimpan pengaturan (HTTP ${r.status})`); return; }
      setSettings(draft);
      setDraft(null);
      toast.success('Pengaturan biaya tersimpan');
      if (selected) computeHPP(selected.id);
    } finally {
      setSavingSettings(false);
    }
  };

  const snapshot = async () => {
    if (!selected) return;
    const r = await fetch(`/api/production-jobs/${selected.id}/hpp-snapshot`, { method: 'POST', headers });
    if (r.ok) {
      toast.success('HPP job tersimpan sebagai catatan');
    }
  };

  // Tahap 1 (6 Nov 2026): job belum menyimpan estimasi HPP. Dulu estimasi = aktual × 0,95
  // (angka karangan); sekarang ditampilkan "belum ada data".
  const detail = selected && (
    <DetailPanel
      testId="hpp-detail-panel"
      title={hpp?.job_number || selected.job_number || selected.wo_number}
      description={hpp ? `PO ${hpp.po_number || selected.po_number || '—'} · qty selesai ${hpp.qty_completed ?? hpp.qty ?? 0} pcs` : 'Menghitung HPP…'}
      onClose={() => { setSelected(null); setHpp(null); }}
      actions={hpp && (
        <Button onClick={snapshot} title="Simpan HPP job ini sebagai catatan" data-testid="hpp-snapshot">
          <Save className="w-4 h-4" />Simpan HPP
        </Button>
      )}
    >
      {!hpp ? (
        <Skeleton className="h-32 w-full" />
      ) : (
        <div className="space-y-4" data-testid="hpp-detail">
          <HppComparisonInline estimated={null} actual={hpp.total_cost} />
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Figure label="Bahan" value={fmt(hpp.material_cost)} testId="hpp-material-cost" />
            <Figure label="Upah CMT" value={fmt(hpp.cmt_cost ?? hpp.labor_cost)} testId="hpp-labor-cost" />
            <Figure label="Total biaya" value={fmt(hpp.total_cost)} />
            <Figure label="HPP per pcs" value={fmt(hpp.hpp_unit)} testId="hpp-unit-actual" strong />
            <Figure label="Upah internal (tidak masuk HPP)" value={fmt(hpp.internal_labor_cost || 0)} />
          </div>
          {(hpp.gaps || []).length > 0 && (
            <div className="space-y-1" data-testid="hpp-gaps">
              <p className="text-sm font-semibold text-foreground">Yang belum lengkap</p>
              {hpp.gaps.map((g, i) => (
                <p key={i} className="text-sm text-muted-foreground"><StatusBadge tone="warning" label="Perlu dilengkapi" /> {g}</p>
              ))}
            </div>
          )}
          <div className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Rincian bahan ({hpp.material_breakdown?.length || 0})</p>
            {(!hpp.material_breakdown || hpp.material_breakdown.length === 0) ? (
              <p className="text-sm text-muted-foreground">Job ini belum punya pengeluaran bahan; angka bahan di atas memakai total agregat.</p>
            ) : (
              <BreakdownTable columns={MATERIAL_COLS} rows={hpp.material_breakdown} />
            )}
          </div>
          <div className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Rincian upah CMT ({hpp.cmt_breakdown?.length || 0})</p>
            {(!hpp.cmt_breakdown || hpp.cmt_breakdown.length === 0) ? (
              <p className="text-sm text-muted-foreground">Job ini belum punya barang jadi atau tarif jahit SPK.</p>
            ) : (
              <BreakdownTable columns={CMT_COLS} rows={hpp.cmt_breakdown} />
            )}
          </div>
          <div className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Rincian upah internal — tidak masuk HPP ({hpp.labor_breakdown?.length || 0})</p>
            {(!hpp.labor_breakdown || hpp.labor_breakdown.length === 0) ? (
              <p className="text-sm text-muted-foreground">Job ini belum punya hasil produksi bertanda; angka upah di atas memakai total agregat.</p>
            ) : (
              <BreakdownTable columns={LABOR_COLS} rows={hpp.labor_breakdown} />
            )}
          </div>
        </div>
      )}
    </DetailPanel>
  );

  const setD = (k, v) => setDraft(s => ({ ...s, [k]: v }));

  return (
    <PageLayout
      testId={page.testId}
      title={page.title}
      subtitle={page.subtitle}
      filters={page.chips}
      tools={<>
        <Button variant="outline" size="icon" onClick={fetchAll} title="Muat ulang" aria-label="Muat ulang" data-testid="hpp-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <Button variant="outline" onClick={() => setDraft({ ...settings })} disabled={!settings} data-testid="hpp-open-settings">
          <Settings2 className="w-4 h-4" />Pengaturan biaya
        </Button>
      </>}
      summary={settings && (
        <p className="text-sm text-muted-foreground" data-testid="hpp-settings-summary">
          Pengaturan biaya: overhead {fmt(settings.overhead_rate_per_pcs || 0)}/pcs (tidak masuk HPP) · harga bawaan bila harga bahan belum ada (dilabeli estimasi) {fmt(readNumber(settings, FIELD.defaultMaterialCostPerKg))}/kg ·
          aksesori bawaan {fmt(settings.default_accessory_cost_per_unit || 0)}/unit · upah cadangan {fmt(settings.labor_rate_fallback_per_pcs || 0)}/pcs
        </p>
      )}
      detail={detail}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : wos.length === 0 ? (
          <EmptyState icon={Factory} title="Belum ada job produksi internal" description="Job produksi internal yang dibuat di portal Produksi muncul di sini." />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="hpp-wo-table">
                <thead><tr><th className="text-left">Job produksi</th><th className="text-left">PO</th><th className="text-left">Status</th></tr></thead>
                <tbody>
                  {paged.map(w => (
                    <tr key={w.id} className={`border-t border-[var(--glass-border)] ${selected?.id === w.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}>
                      <td className="whitespace-nowrap">
                        <Button variant="link" size="sm" className="h-auto p-0" onClick={() => openJob(w)} data-testid={`hpp-wo-${w.job_number || w.wo_number}`}>
                          {w.job_number || w.wo_number}
                        </Button>
                      </td>
                      <td className="whitespace-nowrap text-muted-foreground">{w.po_number || '—'}</td>
                      <td><JobStatus status={w.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {totalPages > 1 && <div className="px-4 py-2"><PaginationLite page={pg} totalPages={totalPages} total={wos.length} pageSize={25} onPageChange={setPage} /></div>}
          </>
        )}
      </GlassCard>

      {draft && (
        <Modal title="Pengaturan biaya bawaan" onClose={() => setDraft(null)} size="md">
          <div className="space-y-4" data-testid="hpp-settings">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="block space-y-1">
                <span className="text-xs text-muted-foreground">Overhead per pcs</span>
                <MoneyInput glass value={draft.overhead_rate_per_pcs || 0}
                  onChange={e => setD('overhead_rate_per_pcs', Number(e.target.value))} data-testid="hpp-overhead-pcs" />
              </label>
              <label className="block space-y-1">
                <span className="text-xs text-muted-foreground">Harga bahan bawaan per kg</span>
                <MoneyInput glass value={readNumber(draft, FIELD.defaultMaterialCostPerKg)}
                  onChange={e => setD('default_material_cost_per_kg', Number(e.target.value))} data-testid="hpp-yarn-kg" />
              </label>
              <label className="block space-y-1">
                <span className="text-xs text-muted-foreground">Aksesori bawaan per unit</span>
                <MoneyInput glass value={draft.default_accessory_cost_per_unit || 0}
                  onChange={e => setD('default_accessory_cost_per_unit', Number(e.target.value))} />
              </label>
              <label className="block space-y-1">
                <span className="text-xs text-muted-foreground">Upah cadangan per pcs</span>
                <MoneyInput glass value={draft.labor_rate_fallback_per_pcs || 0}
                  onChange={e => setD('labor_rate_fallback_per_pcs', Number(e.target.value))} />
              </label>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDraft(null)}>Batal</Button>
              <Button onClick={saveSettings} disabled={savingSettings} data-testid="hpp-save-settings">
                <Save className="w-4 h-4" />
                {savingSettings ? 'Menyimpan…' : 'Simpan pengaturan'}
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </PageLayout>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 2: HPP aktual order maklon
// ══════════════════════════════════════════════════════════════════════════════
function MaklonActualTab({ headers, page }) {
  const [orders, setOrders] = useState([]);
  const [selectedOrderId, setSelectedOrderId] = useState('');
  const [hpp, setHpp] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchOrders = async () => {
      try {
        const r = await fetch('/api/dewi/maklon/pos', { headers });
        if (r.ok) {
          const data = posToLegacyOrders(await r.json());
          setOrders(data.filter(o => !['draft', 'cancelled'].includes(o.status)));
        }
      } catch (e) {
        toast.error('Gagal memuat order maklon');
      }
    };
    fetchOrders();
  }, [headers]);

  const loadHPP = async (orderId) => {
    if (!orderId) return;
    setLoading(true);
    try {
      const r = await fetch(`/api/rahaza/hpp/maklon-order/${orderId}`, { headers });
      if (r.ok) {
        setHpp(await r.json());
      } else {
        toast.error('Gagal memuat HPP order maklon');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleOrderSelect = (orderId) => {
    setSelectedOrderId(orderId);
    loadHPP(orderId);
  };

  const ready = !loading && hpp;

  return (
    <PageLayout
      testId={page.testId}
      title={page.title}
      subtitle={page.subtitle}
      filters={<>
        {page.chips}
        <SmartNativeSelect value={selectedOrderId} onChange={e => handleOrderSelect(e.target.value)}
          className="h-9 w-96 max-w-full" aria-label="Order maklon" data-testid="maklon-order-select">
          <option value="">Pilih order maklon…</option>
          {orders.map(o => (
            <option key={o.id} value={o.id}>{`${o.order_code} — ${o.product_name} (${o.qty_ordered} pcs)`}</option>
          ))}
        </SmartNativeSelect>
      </>}
      summary={ready && <>
        <p className="text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{hpp.order_code}</span> · {hpp.client_name} · {hpp.product_name} · {hpp.qty_ordered} pcs
        </p>
        <HppComparisonInline estimated={hpp.estimated_hpp_total} actual={hpp.total_cost_actual} />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatTile label="Bahan" value={fmt(hpp.material_cost_actual)} testId="maklon-hpp-material" />
          <StatTile label="Upah internal (tidak masuk HPP)" value={fmt(hpp.labor_cost_actual)} testId="maklon-hpp-labor" />
          <StatTile label="Overhead (tidak masuk HPP)" value={fmt(hpp.overhead_cost_actual)} />
          <StatTile label="HPP per pcs" value={fmt(hpp.hpp_unit_actual)} accent="primary" testId="maklon-hpp-unit" />
        </div>
      </>}
    >
      {loading ? (
        <Skeleton className="h-48 w-full rounded-[var(--radius-lg)]" />
      ) : hpp ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
          <GlassCard className="p-4 space-y-2">
            <p className="text-sm font-semibold text-foreground">Rincian bahan</p>
            {(!hpp.material_breakdown || hpp.material_breakdown.length === 0) ? (
              <EmptyState className="py-6" title="Belum ada pengeluaran bahan" description="Bahan yang dikeluarkan untuk order ini muncul di sini." />
            ) : (
              <BreakdownTable columns={MATERIAL_COLS.filter(c => ['name', 'qty', 'amount'].includes(c.key))} rows={hpp.material_breakdown} />
            )}
          </GlassCard>
          <GlassCard className="p-4 space-y-2">
            <p className="text-sm font-semibold text-foreground">Rincian upah</p>
            {(!hpp.labor_breakdown || hpp.labor_breakdown.length === 0) ? (
              <EmptyState className="py-6" title="Belum ada upah produksi" description="Upah dari hasil produksi order ini muncul di sini." />
            ) : (
              <BreakdownTable columns={LABOR_COLS.filter(c => ['op', 'proc', 'amount'].includes(c.key))} rows={hpp.labor_breakdown} />
            )}
          </GlassCard>
        </div>
      ) : (
        <GlassCard className="p-0">
          {selectedOrderId
            ? <EmptyState icon={Calculator} title="Tidak ada data HPP untuk order ini" description="Pilih order lain atau periksa produksi order ini." />
            : <EmptyState icon={Calculator} title="Pilih order maklon" description="Perhitungan HPP aktual order yang dipilih tampil di sini." />}
        </GlassCard>
      )}
    </PageLayout>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 3: Analisa per klien
// ══════════════════════════════════════════════════════════════════════════════
function ClientAnalysisTab({ headers, page }) {
  const [clients, setClients] = useState([]);
  const [selectedClientId, setSelectedClientId] = useState('');
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchClients = async () => {
      try {
        const r = await fetch('/api/dewi/maklon/clients', { headers });
        if (r.ok) {
          const data = await r.json();
          setClients(data.filter(c => c.status === 'active'));
        }
      } catch (e) {
        toast.error('Gagal memuat daftar klien');
      }
    };
    fetchClients();
  }, [headers]);

  const loadAnalysis = async (clientId) => {
    if (!clientId) return;
    setLoading(true);
    try {
      const r = await fetch(`/api/rahaza/hpp/maklon-client/${clientId}`, { headers });
      if (r.ok) {
        setAnalysis(await r.json());
      } else {
        toast.error('Gagal memuat analisa klien');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleClientSelect = (clientId) => {
    setSelectedClientId(clientId);
    loadAnalysis(clientId);
  };

  const download = async (ext) => {
    if (!selectedClientId) return;
    try {
      const r = await fetch(`/api/dewi/reports/maklon/client/${selectedClientId}/export.${ext}`, { headers });
      if (!r.ok) { toast.error(`Gagal mengunduh (HTTP ${r.status})`); return; }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `client_analysis_${selectedClientId}_${todayWIB()}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(`Gagal mengunduh: ${e.message}`);
    }
  };

  const ready = !loading && analysis;

  return (
    <PageLayout
      testId={page.testId}
      title={page.title}
      subtitle={page.subtitle}
      filters={<>
        {page.chips}
        <SmartNativeSelect value={selectedClientId} onChange={e => handleClientSelect(e.target.value)}
          className="h-9 w-80 max-w-full" aria-label="Klien maklon" data-testid="client-select">
          <option value="">Pilih klien…</option>
          {clients.map(c => <option key={c.id} value={c.id}>{`${c.code} — ${c.name}`}</option>)}
        </SmartNativeSelect>
      </>}
      tools={analysis && <>
        <Button variant="outline" onClick={() => download('csv')} data-testid="report-export-csv-button"><Download className="w-4 h-4" />Unduh CSV</Button>
        <Button variant="outline" onClick={() => download('xlsx')} data-testid="report-export-excel-button"><FileSpreadsheet className="w-4 h-4" />Unduh Excel</Button>
      </>}
      summary={loading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">{[1, 2, 3, 4].map(i => <Skeleton key={i} className="h-20" />)}</div>
      ) : ready && <>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatTile label="Jumlah order" value={analysis.total_orders} testId="client-report-total-orders" />
          <StatTile label="Total qty" value={`${analysis.total_qty.toLocaleString('id-ID')} pcs`} />
          <StatTile label="Pendapatan" value={fmt(analysis.total_revenue)} testId="client-report-revenue" />
          <StatTile label="Margin" value={analysis.margin_pct == null ? NO_DATA : pct(analysis.margin_pct)} accent={analysis.margin_pct < 0 ? 'danger' : 'default'} testId="client-report-margin-kpi" />
        </div>
        {analysis.total_hpp_actual == null ? (
          <p className="text-sm text-muted-foreground" data-testid="client-report-hpp-note">
            Biaya bahan tercatat {fmt(analysis.total_material_cost)}. HPP dan margin belum ada data karena upah dan overhead order maklon belum tercatat.
          </p>
        ) : (
          <HppComparisonInline estimated={analysis.total_hpp_estimated} actual={analysis.total_hpp_actual} />
        )}
      </>}
    >
      {ready ? (
        <GlassCard className="p-0 overflow-hidden">
          <div className="px-4 py-3 border-b border-[var(--glass-border)]">
            <p className="text-sm font-semibold text-foreground">Rincian order ({analysis.orders.length})</p>
          </div>
          {analysis.orders.length === 0 ? (
            <EmptyState title="Belum ada order untuk klien ini" description="Order maklon klien ini muncul di sini." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="client-analysis-table">
                <thead>
                  <tr>
                    <th className="text-left">Kode order</th>
                    <th className="text-left">Produk</th>
                    <th className="text-right">Qty</th>
                    <th className="text-left">Status</th>
                    <th className="text-right">Pendapatan</th>
                    <th className="text-right">Biaya bahan</th>
                    <th className="text-right">HPP aktual</th>
                    <th className="text-right">Margin</th>
                    <th className="text-center">Tepat waktu</th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.orders.map((order, i) => (
                    <tr key={i} className="border-b border-[var(--glass-border)] hover:bg-[var(--glass-bg-hover)]" data-testid="client-analysis-row">
                      <td className="whitespace-nowrap">{order.order_code}</td>
                      <td>{order.product_name}</td>
                      <td className="text-right tabular-nums">{order.qty}</td>
                      <td><JobStatus status={order.status} /></td>
                      <td className="text-right tabular-nums">{fmt(order.revenue)}</td>
                      <td className="text-right tabular-nums">{fmt(order.material_cost)}</td>
                      <td className="text-right tabular-nums">{order.hpp_actual == null ? '–' : fmt(order.hpp_actual)}</td>
                      <td className={`text-right tabular-nums ${order.margin > 0 ? 'text-[hsl(var(--success))]' : order.margin < 0 ? 'text-[hsl(var(--destructive))]' : 'text-muted-foreground'}`}>
                        {order.margin == null ? '–' : fmt(order.margin)}
                      </td>
                      <td className="text-center">
                        {order.is_on_time === true ? (
                          <span className="text-[hsl(var(--success))]" title="Tepat waktu">✓</span>
                        ) : order.is_on_time === false ? (
                          <span className="text-[hsl(var(--destructive))]" title="Terlambat">✗</span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>
      ) : !loading && (
        <GlassCard className="p-0">
          {selectedClientId
            ? <EmptyState icon={Building2} title="Tidak ada data untuk klien ini" description="Pilih klien lain atau periksa order maklon klien ini." />
            : <EmptyState icon={Building2} title="Pilih klien maklon" description="Ringkasan order, pendapatan, margin, dan HPP klien tampil di sini." />}
        </GlassCard>
      )}
    </PageLayout>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 4: Sisa WIP per PO (2026-11-06, Tahap 2) — bahan aktual vs standar BOM yang dikredit lapisan FG.
// Sisa PO yang sudah ditutup dipindah ke Selisih Produksi otomatis saat PO ditutup; PO lama bisa
// ditutup Keuangan di sini. Rincian per sumber dibuka di halaman (DetailPanel), konfirmasi di dialog.
// ══════════════════════════════════════════════════════════════════════════════
const WIP_COLS = [
  { key: 'label', label: 'Sumber', render: (g) => g.label },
  { key: 'debit', label: 'Masuk WIP', right: true, render: (g) => fmt(g.debit) },
  { key: 'credit', label: 'Keluar WIP', right: true, render: (g) => fmt(g.credit) },
  { key: 'net', label: 'Bersih', right: true, render: (g) => fmt(g.net) },
];
const WIP_ROW_COLS = (open) => [
  { key: 'po', label: 'PO', render: (r) => (
    <Button variant="link" size="sm" className="h-auto p-0" onClick={() => open(r)} data-testid={`po-wip-${r.po_number}`}>{r.po_number || r.po_id}</Button>
  ) },
  { key: 'status', label: 'Status', muted: true, render: (r) => <JobStatus status={r.status} /> },
  { key: 'residual', label: 'Sisa WIP', right: true, render: (r) => fmt(r.residual) },
];

function PoWipTab({ headers, page }) {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/costing/po-wip', { headers });
      const d = r.ok ? await r.json() : { items: [] };
      setRows(d.items || []);
      setTotal(d.total_residual || 0);
    } finally {
      setLoading(false);
    }
  }, [headers]);
  useEffect(() => { load(); }, [load]);

  const clear = async () => {
    setBusy(true);
    try {
      const r = await fetch(`/api/costing/po-wip/${confirm.po_id}/clear`, { method: 'POST', headers });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { toast.error(d.detail || `Gagal menutup sisa WIP (HTTP ${r.status})`); return; }
      toast.success(`Sisa WIP PO ${confirm.po_number} dipindah ke selisih produksi.`);
      setConfirm(null); setSelected(null);
      load();
    } finally {
      setBusy(false);
    }
  };

  const detail = selected && (
    <DetailPanel testId="po-wip-detail" title={`PO ${selected.po_number || selected.po_id}`}
      description={`Sisa WIP ${fmt(selected.residual)} — bahan & upah yang masuk WIP dikurangi nilai yang sudah pindah ke barang jadi.`}
      onClose={() => setSelected(null)}
      actions={<Button onClick={() => setConfirm(selected)} data-testid="po-wip-clear">Tutup sisa WIP</Button>}>
      <BreakdownTable columns={WIP_COLS} rows={selected.groups || []} testId="po-wip-groups" />
    </DetailPanel>
  );

  return (
    <PageLayout testId={page.testId} title={page.title} subtitle={page.subtitle} filters={page.chips}
      tools={<Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="w-4 h-4" /></Button>}
      summary={!loading && (
        <p className="text-sm text-muted-foreground" data-testid="po-wip-summary">
          {rows.length} PO yang sudah ditutup masih menyisakan WIP, total {fmt(total)}. Saat PO ditutup, sisanya otomatis dipindah ke akun selisih produksi.
        </p>
      )}
      detail={detail}>
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : rows.length === 0 ? (
          <EmptyState icon={Calculator} title="Tidak ada sisa WIP" description="Semua PO produksi yang sudah ditutup sudah bersih dari saldo WIP." />
        ) : (
          <BreakdownTable columns={WIP_ROW_COLS(setSelected)} rows={rows} testId="po-wip-table" />
        )}
      </GlassCard>
      {confirm && (
        <Modal title="Tutup sisa WIP" onClose={() => setConfirm(null)} size="sm">
          <div className="space-y-4">
            <p className="text-sm text-foreground">
              Sisa WIP PO {confirm.po_number} sebesar {fmt(confirm.residual)} dipindah ke akun selisih produksi dengan satu jurnal.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setConfirm(null)}>Batal</Button>
              <Button onClick={clear} disabled={busy} data-testid="po-wip-confirm">{busy ? 'Menyimpan…' : 'Tutup sisa WIP'}</Button>
            </div>
          </div>
        </Modal>
      )}
    </PageLayout>
  );
}

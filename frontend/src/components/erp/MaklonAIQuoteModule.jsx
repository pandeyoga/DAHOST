/**
 * MaklonAIQuoteModule — tab "Estimasi harga" di menu Klien & Katalog Buyer (Portal Maklon).
 *
 * Perkiraan harga jasa maklon dari rincian produk: HPP per pcs, margin, waktu kerja, risiko & saran.
 * Hitungan bawaan memakai rumus (heuristik); bila AI aktif, hasilnya diperhalus AI lalu dirapikan dengan
 * aturan biaya owner (bahan dari klien & biaya umum bukan HPP; margin atas harga jual) — lihat
 * `routes/dewi_maklon_quote.py`.
 *
 * Tahap 9 (7 Nov 2026, keputusan owner): "Estimasi AI Maklon" pindah ke Katalog Buyer sebagai tab.
 * Cetakan PageLayout: daftar estimasi = tabel (bisa diunduh); rincian = popup (DetailPanel).
 * Standar UI/UX v2 (8 Nov 2026): estimasi baru = FormPopup panjang; setelah dihitung, rincian estimasi baru langsung
 * terbuka (hasil yang dulu tampil di bawah form kini di popup rincian). Isian & panggilan server tidak berubah.
 *
 *   POST /api/maklon/ai-quote/generate · GET /api/maklon/ai-quote/history
 *   POST /api/maklon/ai-quote/{id}/accept · DELETE /api/maklon/ai-quote/{id}
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Calculator, CheckCircle2, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { apiDelete, apiGet, apiPost, getToken } from '../../lib/api';
import { formatDateTimeID, formatRupiah } from '@/lib/format';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import BuyerCatalogSelect from './pickers/BuyerCatalogSelect';

const CATEGORY_OPTIONS = { kaos: 'Kaos', kemeja: 'Kemeja', hijab: 'Hijab', celana: 'Celana', outerwear: 'Jaket / luaran', general: 'Lainnya' };
const MARKET_OPTIONS = { mass: 'Pasar massal', mid: 'Menengah', premium: 'Premium', luxury: 'Mewah' };
const COMPETITIVE = { high: ['Bersaing', 'success'], medium: ['Sedang', 'warning'], low: ['Mahal', 'danger'] };
const QUOTE_STATUS = { draft: ['Draf', 'muted'], accepted: ['Diterima', 'success'] };
const SOURCE_LABEL = {
  ai: 'Diperhalus AI', heuristic: 'Rumus bawaan', heuristic_budget_exceeded: 'Rumus bawaan (batas biaya AI tercapai)',
  heuristic_after_ai_error: 'Rumus bawaan (AI gagal)', heuristic_after_ai_parse_fail: 'Rumus bawaan (jawaban AI tidak terbaca)',
};
const EMPTY_FORM = {
  product_name: '', buyer_catalog_id: '', is_new_article: true, category: 'kaos', quantity: 1000, target_market: 'mid',
  target_unit_price: '', materials: '', finishing: '', required_lead_time_days: '', client_name: '', additional_notes: '',
  target_margin_pct: 25, fabric_provided_by: 'client',
};
const fmtRp = (v) => (v == null ? '—' : formatRupiah(v));

/** Isian standar; tanda * di label → `wajib`. */
function Field({ label, children, className = '' }) {
  const wajib = /\*\s*$/.test(label);
  return <Isian label={label.replace(/\s*\*\s*$/, '')} wajib={wajib} className={className}>{children}</Isian>;
}

export function QuoteResult({ result }) {
  const res = result?.result || result;
  if (!res) return null;
  // bahan dari klien bukan biaya DA — hasil AI menandai `material_supplied_by`, hasil rumus mengikuti isian permintaan
  const clientMaterial = res.material_supplied_by
    ? res.material_supplied_by === 'client' : (result?.request?.fabric_provided_by || 'client') !== 'cv_da';
  const [cLabel, cTone] = COMPETITIVE[res.competitiveness] || [null, null];
  const bd = res.hpp_breakdown || {};
  return (
    <div className="space-y-3" data-testid="quote-result">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile label="Perkiraan harga per pcs" value={fmtRp(res.estimated_unit_price)} accent="success"
          sub={cLabel ? `Daya saing: ${cLabel}` : undefined} subTone={cTone || undefined} testId="quote-unit-price" />
        <StatTile label="Total order" value={fmtRp(res.estimated_total)} />
        <StatTile label="Margin" value={`${Number(res.margin_pct || 0).toLocaleString('id-ID', { maximumFractionDigits: 1 })}%`} sub={fmtRp(res.margin_amount)} />
        <StatTile label="Perkiraan waktu kerja" value={res.estimated_lead_time_days ? `${res.estimated_lead_time_days} hari` : '—'} />
      </div>
      {res.hpp_breakdown && (
        <Table>
          <TableHeader><TableRow><TableHead>HPP per pcs</TableHead><TableHead className="text-right">Nilai</TableHead></TableRow></TableHeader>
          <TableBody>
            <TableRow><TableCell>{clientMaterial ? 'Bahan (dari klien, tidak dihitung)' : 'Bahan'}</TableCell><TableCell className="text-right tabular-nums">{fmtRp(bd.material)}</TableCell></TableRow>
            <TableRow><TableCell>Upah CMT</TableCell><TableCell className="text-right tabular-nums">{fmtRp(bd.labor)}</TableCell></TableRow>
            <TableRow><TableCell>Finishing</TableCell><TableCell className="text-right tabular-nums">{fmtRp(bd.finishing)}</TableCell></TableRow>
            <TableRow><TableCell>Biaya umum (tidak masuk HPP)</TableCell><TableCell className="text-right tabular-nums">{fmtRp(bd.overhead)}</TableCell></TableRow>
            <TableRow><TableCell className="font-semibold">Jumlah HPP</TableCell><TableCell className="text-right tabular-nums font-semibold">{fmtRp(res.hpp_per_pcs)}</TableCell></TableRow>
          </TableBody>
        </Table>
      )}
      {res.summary && <p className="text-sm text-muted-foreground whitespace-pre-wrap">{res.summary}</p>}
      {res.risks?.length > 0 && (
        <Notice tone="warning" icon={AlertTriangle} title="Risiko">
          <ul className="list-disc pl-4 text-xs space-y-0.5">{res.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </Notice>
      )}
      {res.recommendations?.length > 0 && (
        <Notice tone="info" icon={CheckCircle2} title="Saran">
          <ul className="list-disc pl-4 text-xs space-y-0.5">{res.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </Notice>
      )}
      {res.source && <p className="text-xs text-muted-foreground text-right">Sumber hitungan: {SOURCE_LABEL[res.source] || 'Rumus bawaan'}</p>}
    </div>
  );
}

function NewQuotePanel({ onClose, onCreated }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const generate = async () => {
    if (!form.product_name?.trim()) { toast.error('Nama produk wajib diisi'); return; }
    if (!form.quantity || Number(form.quantity) <= 0) { toast.error('Jumlah harus lebih dari 0'); return; }
    setBusy(true);
    try {
      const d = await apiPost('/maklon/ai-quote/generate', {
        ...form, quantity: Number(form.quantity),
        target_unit_price: form.target_unit_price ? Number(form.target_unit_price) : null,
        required_lead_time_days: form.required_lead_time_days ? Number(form.required_lead_time_days) : null,
        target_margin_pct: Number(form.target_margin_pct) || 25,
      });
      toast.success('Estimasi harga dibuat');
      onCreated(d?.data?.id);
    } catch (e) { toast.error(`Gagal membuat estimasi: ${e.message}`); }
    finally { setBusy(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="quote-new-panel" judul="Estimasi harga baru"
      keterangan="Isi rincian produk; hasilnya tersimpan di daftar estimasi dan rinciannya langsung dibuka. Perhitungan 10–30 detik."
      onSimpan={generate} menyimpan={busy} labelSimpan="Hitung estimasi">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          {/* F14b — artikel yang SUDAH ada di Katalog Buyer dipilih, bukan diketik ulang; artikel baru boleh diketik. */}
          <BuyerCatalogSelect token={getToken()} value={form.buyer_catalog_id} newName={form.product_name} label="Produk / artikel"
            testId="quote-product-select"
            onPick={(cat) => setForm((p) => ({ ...p, buyer_catalog_id: cat?.id || '', is_new_article: !cat,
              product_name: cat?.product_name || '', client_name: cat?.client_name || p.client_name, materials: cat?.description || p.materials }))}
            onNewName={(v) => setForm((p) => ({ ...p, product_name: v, buyer_catalog_id: '', is_new_article: true }))} />
        </div>
        <Field label="Kategori">
          <SmartNativeSelect value={form.category} onChange={set('category')} className="w-full h-9" searchable={false} aria-label="Kategori">
            {Object.entries(CATEGORY_OPTIONS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SmartNativeSelect>
        </Field>
        <Field label="Target pasar">
          <SmartNativeSelect value={form.target_market} onChange={set('target_market')} className="w-full h-9" searchable={false} aria-label="Target pasar">
            {Object.entries(MARKET_OPTIONS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SmartNativeSelect>
        </Field>
        <Field label="Jumlah (pcs) *"><Input type="number" value={form.quantity} onChange={set('quantity')} data-testid="quote-qty" /></Field>
        <Field label="Target harga per pcs (opsional)"><MoneyInput value={form.target_unit_price} onChange={set('target_unit_price')} /></Field>
        <Field label="Margin (% dari harga jual)"><Input type="number" value={form.target_margin_pct} onChange={set('target_margin_pct')} /></Field>
        <Field label="Waktu kerja diminta klien (hari)"><Input type="number" value={form.required_lead_time_days} onChange={set('required_lead_time_days')} placeholder="opsional" /></Field>
        <Field label="Bahan utama disediakan oleh">
          <SmartNativeSelect value={form.fabric_provided_by} onChange={set('fabric_provided_by')} className="w-full h-9" searchable={false}
            data-testid="quote-fabric-provider" aria-label="Bahan utama disediakan oleh">
            <option value="client">Klien (tidak dihitung sebagai biaya)</option>
            <option value="cv_da">CV Dewi Aditya (masuk biaya)</option>
          </SmartNativeSelect>
        </Field>
        <Field label="Nama klien"><Input value={form.client_name} onChange={set('client_name')} /></Field>
        <Field label="Bahan" className="sm:col-span-2"><Input value={form.materials} onChange={set('materials')} placeholder="mis. katun combed 30s, 180 gsm" /></Field>
        <Field label="Finishing" className="sm:col-span-2"><Input value={form.finishing} onChange={set('finishing')} placeholder="mis. sablon + bordir logo" /></Field>
        <Field label="Catatan tambahan" className="sm:col-span-2"><Textarea rows={2} value={form.additional_notes} onChange={set('additional_notes')} placeholder="Spesifikasi khusus, kemasan, dll." /></Field>
      </div>
    </FormPopup>
  );
}

function QuoteDetail({ quote, onClose, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [label, tone] = QUOTE_STATUS[quote.status] || [quote.status || 'Draf', 'muted'];
  const accept = async () => {
    if (!(await confirmDialog({ title: 'Tandai estimasi ini diterima klien?', body: 'Hanya menandai — PO maklon tetap dibuat dari menu PO Maklon.',
      confirmLabel: 'Tandai diterima' }))) return;
    setBusy(true);
    try { await apiPost(`/maklon/ai-quote/${quote.id}/accept`, {}); toast.success('Estimasi ditandai diterima'); await onChanged(quote.id); }
    catch (e) { toast.error(e.message || 'Gagal'); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!(await confirmDialog({ title: 'Hapus estimasi ini?', body: 'Estimasi dihapus dari daftar.', confirmLabel: 'Hapus estimasi', danger: true }))) return;
    setBusy(true);
    try { await apiDelete(`/maklon/ai-quote/${quote.id}`); toast.success('Estimasi dihapus'); onClose(); await onChanged(null); }
    catch (e) { toast.error(e.message || 'Gagal menghapus'); }
    finally { setBusy(false); }
  };
  const rq = quote.request || {};
  return (
    <DetailPanel testId="quote-detail" onClose={onClose}
      title={<span className="inline-flex items-center gap-2 flex-wrap">{rq.product_name || 'Estimasi'} <StatusBadge status={quote.status} label={label} tone={tone} /></span>}
      description={`${quote.created_at ? formatDateTimeID(quote.created_at) : '—'} · ${quote.created_by_name || '—'}`}
      actions={<>
        {quote.status !== 'accepted' && <Button variant="outline" onClick={accept} disabled={busy} data-testid={`quote-accept-${quote.id}`}><CheckCircle2 className="w-4 h-4" />Tandai diterima</Button>}
        <Button variant="destructive" size="icon" onClick={remove} disabled={busy} title="Hapus estimasi" aria-label="Hapus estimasi" data-testid={`quote-delete-${quote.id}`}><Trash2 className="w-4 h-4" /></Button>
      </>}>
      <p className="text-sm text-muted-foreground">
        {CATEGORY_OPTIONS[rq.category] || rq.category || '—'} · {Number(rq.quantity || 0).toLocaleString('id-ID')} pcs · klien {rq.client_name || '—'}
        {rq.is_new_article === false ? ' · artikel dari Katalog Buyer' : ' · artikel baru (belum di katalog)'}
      </p>
      <QuoteResult result={quote} />
    </DetailPanel>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
export default function MaklonAIQuoteModule() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [panel, setPanel] = useState(null); // {mode:'new'} | {mode:'view', id}

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { const d = await apiGet('/maklon/ai-quote/history?limit=200'); setRows(Array.isArray(d?.data) ? d.data : []); }
    catch (e) { setError(e.message || 'Gagal memuat estimasi'); setRows([]); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const counts = useMemo(() => ({ all: rows.length, draft: rows.filter((q) => q.status !== 'accepted').length,
    accepted: rows.filter((q) => q.status === 'accepted').length }), [rows]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => (!status || (status === 'accepted' ? r.status === 'accepted' : r.status !== 'accepted'))
      && (!q || `${r.request?.product_name} ${r.request?.client_name}`.toLowerCase().includes(q)));
  }, [rows, search, status]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);
  const current = panel?.mode === 'view' ? rows.find((r) => r.id === panel.id) : null;

  return (
    <PageLayout testId="maklon-ai-quote" title="Estimasi harga"
      subtitle="Perkiraan harga jasa maklon dari rincian produk: HPP, margin, dan waktu kerja."
      actions={<Button onClick={() => setPanel({ mode: 'new' })} data-testid="quote-new-btn"><Plus className="w-4 h-4" />Estimasi baru</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari produk atau klien" className="pl-8"
            data-testid="quote-search" />
        </div>
        <FilterChips value={status} onChange={setStatus} testId="quote-status" ariaLabel="Status estimasi"
          options={[{ key: '', label: 'Semua', count: counts.all }, { key: 'draft', label: 'Draf', count: counts.draft },
            { key: 'accepted', label: 'Diterima', count: counts.accepted }]} />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="estimasi-harga-maklon" namaLembar="Estimasi harga" baris={filtered} testId="quote-unduh"
          kolom={[
            { label: 'Waktu', nilai: (q) => (q.created_at ? formatDateTimeID(q.created_at) : '') },
            { label: 'Produk', nilai: (q) => q.request?.product_name || '' }, { label: 'Klien', nilai: (q) => q.request?.client_name || '' },
            { label: 'Kategori', nilai: (q) => CATEGORY_OPTIONS[q.request?.category] || q.request?.category || '' },
            { label: 'Jumlah (pcs)', nilai: (q) => Number(q.request?.quantity || 0) },
            { label: 'Harga/pcs', nilai: (q) => (q.result?.estimated_unit_price == null ? '' : Number(q.result.estimated_unit_price)) },
            { label: 'Total', nilai: (q) => (q.result?.estimated_total == null ? '' : Number(q.result.estimated_total)) },
            { label: 'HPP/pcs', nilai: (q) => (q.result?.hpp_per_pcs == null ? '' : Number(q.result.hpp_per_pcs)) },
            { label: 'Margin %', nilai: (q) => (q.result?.margin_pct == null ? '' : Number(q.result.margin_pct)) },
            { label: 'Status', nilai: (q) => (QUOTE_STATUS[q.status] || [q.status || 'Draf'])[0] },
          ]} />
        <Button size="icon" variant="outline" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="quote-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={error && <Notice tone="danger" title="Gagal memuat estimasi">{error}</Notice>}
      detail={panel?.mode === 'new'
        ? <NewQuotePanel onClose={() => setPanel(null)} onCreated={async (id) => { await load(); setPanel(id ? { mode: 'view', id } : null); }} />
        : current && <QuoteDetail quote={current} onClose={() => setPanel(null)} onChanged={async (id) => { await load(); setPanel(id ? { mode: 'view', id } : null); }} />}
      footer={filtered.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}>
      <GlassCard className="p-0 overflow-hidden">
        {loading && !rows.length ? (
          <div className="p-4 text-sm text-muted-foreground">Memuat estimasi…</div>
        ) : (
          <Table data-testid="quote-history-table">
            <TableHeader><TableRow>
              <TableHead>Waktu</TableHead><TableHead>Produk</TableHead><TableHead>Klien</TableHead>
              <TableHead className="text-right">Jumlah</TableHead><TableHead className="text-right">Harga/pcs</TableHead>
              <TableHead className="text-right">Total</TableHead><TableHead>Status</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {!paged.length && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={7} className="p-0 [&>div]:py-8">
                    <EmptyState icon={Calculator} title={rows.length ? 'Tidak ada estimasi yang cocok' : 'Belum ada estimasi harga'}
                      description={rows.length ? 'Ubah kata pencarian atau penyaring status.' : 'Klik Estimasi baru untuk menghitung harga jasa maklon.'} />
                  </TableCell>
                </TableRow>
              )}
              {paged.map((q) => {
                const [label, tone] = QUOTE_STATUS[q.status] || [q.status || 'Draf', 'muted'];
                return (
                  <TableRow key={q.id} data-testid={`quote-history-${q.id}`} className={panel?.id === q.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{q.created_at ? formatDateTimeID(q.created_at) : '—'}</TableCell>
                    <TableCell>
                      <Button variant="link" size="sm" className="h-auto p-0 font-semibold text-left" onClick={() => setPanel({ mode: 'view', id: q.id })}
                        data-testid={`quote-open-${q.id}`}>{q.request?.product_name || '—'}</Button>
                    </TableCell>
                    <TableCell className="text-sm">{q.request?.client_name || '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{Number(q.request?.quantity || 0).toLocaleString('id-ID')}</TableCell>
                    <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(q.result?.estimated_unit_price)}</TableCell>
                    <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(q.result?.estimated_total)}</TableCell>
                    <TableCell><StatusBadge status={q.status} label={label} tone={tone} /></TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </GlassCard>
    </PageLayout>
  );
}

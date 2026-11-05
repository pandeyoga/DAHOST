/**
 * POClosureModule (Phase C — 2026-07-17)
 * ──────────────────────────────────────
 * "Tutup PO (Closure)" — panel monitoring pemenuhan PO + penutupan manual.
 *
 * Alur (GUIDELINE_CMT_FLOW.md §11):
 *   • Auto-close: begitu Σqty_received (buyer) ≥ Σqty_ordered, PO otomatis
 *     berstatus "Completed" (closed_reason=full_fulfillment) — terjadi di backend
 *     saat DA set qty_received di modul Dispatch ke Buyer.
 *   • Close short (manual): untuk PO yang tidak akan terpenuhi 100% (deadline lewat,
 *     material buyer kurang, reject CMT final, atau kesepakatan). Pilih alasan →
 *     status "Closed Short", qty_short tercatat, dan Finance disesuaikan:
 *       – AR masih draft → invoice dikecilkan ke qty_received.
 *       – AR sudah issued → dibuat Credit Note draft (Σ short × cmt_rate).
 *
 * SSOT: /api/production-pos, /api/production-pos/{id}/fulfillment,
 *       /api/production-pos/{id}/close-short, /api/production-pos/{id}/credit-notes
 */
import { useEffect, useMemo, useState, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import {
  Lock, RefreshCw, Search, AlertTriangle, CheckCircle2, XCircle,
  Package, Info, Loader2, Scissors, FileWarning, TrendingDown,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import FilterChips from '@/components/ui/filter-chips';
import { EmptyState, Notice } from '../moduleAtoms';
import Modal from './Modal';
import StatusBadge from './StatusBadge';
import { apiGet, apiPost } from '../../../lib/api';
import { formatRupiah } from '@/lib/format';

const REASON_LABELS = {
  deadline_expired: 'Deadline terlewati',
  buyer_material_shortage: 'Material dari buyer kurang',
  cmt_quality_reject_final: 'Reject kualitas CMT (final)',
  mutual_agreement: 'Kesepakatan bersama',
};

const TERMINAL = ['Completed', 'Closed', 'Closed Short'];

function fmtNum(n) { return Number(n || 0).toLocaleString('id-ID'); }
const fmtRp = formatRupiah;
function fmtDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' }); }
  catch { return String(iso).slice(0, 10); }
}

export default function POClosureModule({ portalId }) {
  const businessType = portalId === 'maklon' ? 'maklon' : portalId === 'production' ? 'internal' : null;

  const [rows, setRows] = useState([]);        // [{po, fulfillment}]
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('open');       // open | closed | all
  const [search, setSearch] = useState('');

  const [closing, setClosing] = useState(null); // {po, fulfillment}
  const [reason, setReason] = useState('');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [creditNotes, setCreditNotes] = useState({}); // {po_id: [cn]}

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const q = businessType ? `?business_type=${businessType}` : '';
      const data = await apiGet(`/production-pos${q}`);
      const pos = Array.isArray(data) ? data : (data?.data || []);
      // fulfillment per PO (parallel)
      const settled = await Promise.allSettled(
        pos.map((p) => apiGet(`/production-pos/${p.id}/fulfillment`))
      );
      const merged = pos.map((p, i) => ({
        po: p,
        fulfillment: settled[i].status === 'fulfilled' ? settled[i].value : null,
      }));
      setRows(merged);
    } catch (e) {
      toast.error(`Gagal memuat PO: ${e.message || e}`);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [businessType]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const filtered = useMemo(() => {
    let r = rows;
    if (tab === 'open') r = r.filter((x) => !TERMINAL.includes(x.po.status));
    else if (tab === 'closed') r = r.filter((x) => TERMINAL.includes(x.po.status));
    const s = search.trim().toLowerCase();
    if (s) r = r.filter((x) =>
      (x.po.po_number || '').toLowerCase().includes(s) ||
      (x.po.customer_name || '').toLowerCase().includes(s));
    return r;
  }, [rows, tab, search]);

  const counts = useMemo(() => ({
    open: rows.filter((x) => !TERMINAL.includes(x.po.status)).length,
    closed: rows.filter((x) => TERMINAL.includes(x.po.status)).length,
    all: rows.length,
  }), [rows]);

  const openClose = (row) => {
    setClosing(row);
    setReason('');
    setNotes('');
  };

  const submitClose = async () => {
    if (!reason) { toast.error('Pilih alasan penutupan.'); return; }
    setSubmitting(true);
    try {
      const res = await apiPost(`/production-pos/${closing.po.id}/close-short`, {
        closed_reason: reason, notes,
      });
      const fin = res.finance || {};
      if (fin.credit_note_created) {
        toast.success(`PO ditutup. Credit Note ${fin.credit_note_number} (${fmtRp(fin.amount)}) dibuat.`);
      } else if (fin.ar_adjusted_to_received) {
        toast.success('PO ditutup. Invoice AR draft disesuaikan ke qty diterima.');
      } else {
        toast.success(`PO ditutup (qty_short ${res.qty_short}).`);
      }
      setClosing(null);
      await fetchAll();
    } catch (e) {
      toast.error(`Gagal menutup PO: ${e.message || e}`);
    } finally {
      setSubmitting(false);
    }
  };

  const loadCreditNotes = async (poId) => {
    try {
      const cn = await apiGet(`/production-pos/${poId}/credit-notes`);
      setCreditNotes((m) => ({ ...m, [poId]: Array.isArray(cn) ? cn : [] }));
    } catch { /* ignore */ }
  };

  return (
    <div className="space-y-4" data-testid="po-closure-module">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Lock className="w-6 h-6 text-primary" /> Tutup PO (Closure)
          </h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
            Pantau pemenuhan PO. PO yang <b>terpenuhi 100%</b> otomatis jadi{' '}
            <b>Completed</b>. Untuk PO yang tidak akan terpenuhi penuh, lakukan{' '}
            <b>Close Short</b> dengan alasan — Finance akan menyesuaikan invoice / membuat credit note.
          </p>
        </div>
        <Button
          variant="outline" size="icon"
          onClick={fetchAll}
          title="Muat ulang" aria-label="Muat ulang"
          data-testid="po-closure-refresh"
        >
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </div>

      {/* Phase C banner */}
      <Notice tone="info" icon={Info} title="Aturan penutupan">
        Penutupan memakai <b>qty diterima buyer</b>. PO tertutup otomatis saat jumlah diterima ≥ jumlah
        dipesan. Close Short hanya sah dari status{' '}
        <i>In Production / Production Complete / Variance Review / Return Review / Ready to Close</i>{' '}
        dan bila masih ada kekurangan qty.
      </Notice>

      {/* Tabs + search */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        {/* PANDUAN_UI G4 — penyaring status; testid tiap pil tetap `po-closure-tab-<kunci>` */}
        <div data-testid="po-closure-tabs">
          <FilterChips
            value={tab}
            onChange={setTab}
            testId="po-closure-tab"
            ariaLabel="Penyaring status PO"
            options={[
              { key: 'open', label: 'Perlu ditutup', count: counts.open },
              { key: 'closed', label: 'Sudah ditutup', count: counts.closed },
              { key: 'all', label: 'Semua', count: counts.all },
            ]}
          />
        </div>
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Cari no. PO / buyer…"
            data-testid="po-closure-search"
            className="pl-9 pr-3 py-2 rounded-lg border border-border bg-card text-sm text-foreground w-64 focus:outline-none focus:ring-2 focus:ring-primary/40"
          />
        </div>
      </div>

      {/* Table */}
      <GlassCard className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/60 text-muted-foreground">
              <tr className="text-left">
                <th className="px-4 py-3 font-semibold">NO. PO</th>
                <th className="px-4 py-3 font-semibold">BUYER</th>
                <th className="px-4 py-3 font-semibold text-right whitespace-nowrap">DIPESAN</th>
                <th className="px-4 py-3 font-semibold text-right whitespace-nowrap">PRODUKSI</th>
                <th className="px-4 py-3 font-semibold text-right whitespace-nowrap text-[hsl(var(--destructive))]">DITOLAK</th>
                <th className="px-4 py-3 font-semibold text-right whitespace-nowrap">DIKIRIM</th>
                <th className="px-4 py-3 font-semibold text-right">DITERIMA</th>
                <th className="px-4 py-3 font-semibold text-right">KURANG</th>
                <th className="px-4 py-3 font-semibold">STATUS</th>
                <th className="px-4 py-3 font-semibold text-right">AKSI</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loading ? (
                <tr><td colSpan={10} className="px-4 py-4 text-center text-muted-foreground">
                  <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> Memuat…
                </td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={10}>
                  <EmptyState icon={Package} title="Tidak ada PO pada penyaring ini"
                    description="Pilih penyaring lain atau ubah kata pencarian." />
                </td></tr>
              ) : filtered.map(({ po, fulfillment: f }) => {
                const short = f?.qty_short ?? 0;
                const isTerminal = TERMINAL.includes(po.status);
                const cns = creditNotes[po.id];
                return (
                  <tr key={po.id} className="hover:bg-accent/40" data-testid={`po-closure-row-${po.id}`}>
                    <td className="px-4 py-3 font-medium text-foreground whitespace-nowrap">{po.po_number}</td>
                    <td className="px-4 py-3 text-foreground/80">{po.customer_name || '—'}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{f ? fmtNum(f.total_ordered) : '—'}</td>
                    {/* FASE 1: penutupan PO WAJIB menampilkan "produced X, reject Y" */}
                    <td className="px-4 py-3 text-right tabular-nums font-medium text-[hsl(var(--success))]">
                      {f?.qc ? fmtNum(f.qc.produced) : '—'}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {f?.qc && Number(f.qc.reject || 0) > 0 ? (
                        <span className="font-semibold text-[hsl(var(--destructive))] whitespace-nowrap">
                          {fmtNum(f.qc.reject)}
                          <span className="text-[10px] opacity-80"> ({f.qc.reject_rate_pct}%)</span>
                          {Number(f.qc.rework_open || 0) > 0 && (
                            <span className="block text-[10px] font-medium text-[hsl(var(--warning))]">
                              {fmtNum(f.qc.rework_open)} rework
                            </span>
                          )}
                        </span>
                      ) : <span className="text-[hsl(var(--success))]">0</span>}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{f ? fmtNum(f.total_shipped) : '—'}</td>
                    <td className="px-4 py-3 text-right tabular-nums font-medium">{f ? fmtNum(f.total_received) : '—'}</td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {f && short > 0 ? (
                        <span className="inline-flex items-center gap-1 text-[hsl(var(--warning))] font-medium">
                          <TrendingDown className="w-3.5 h-3.5" /> {fmtNum(short)}
                          <span className="text-xs opacity-70">({f.qty_short_pct}%)</span>
                        </span>
                      ) : (
                        <span className="text-[hsl(var(--success))]">0</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-1">
                        <StatusBadge status={po.status} />
                        {po.closed_reason && (
                          <span className="text-[11px] text-muted-foreground">
                            {REASON_LABELS[po.closed_reason] || po.closed_reason}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {f?.can_close_short ? (
                        <Button
                          variant="outline" size="sm"
                          onClick={() => openClose({ po, fulfillment: f })}
                          data-testid={`po-close-short-btn-${po.id}`}
                          className="text-[hsl(var(--warning))]"
                        >
                          <Scissors className="w-3.5 h-3.5" /> Close Short
                        </Button>
                      ) : isTerminal ? (
                        <Button
                          variant="outline" size="sm"
                          onClick={() => loadCreditNotes(po.id)}
                          className="text-muted-foreground"
                        >
                          {cns ? `${cns.length} CN` : 'Lihat CN'}
                        </Button>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                      {cns && cns.length > 0 && (
                        <div className="mt-1 text-[11px] text-[hsl(var(--warning))] flex items-center gap-1 justify-end">
                          <FileWarning className="w-3 h-3" /> {cns[0].credit_note_number} · {fmtRp(cns[0].total_amount)}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </GlassCard>

      {/* Close Short modal */}
      {closing && (
        <Modal title="Tutup PO — Close Short" onClose={() => setClosing(null)} size="md">
          <div className="space-y-4" data-testid="po-close-short-modal">
            <div className="rounded-lg bg-muted/50 p-3 text-sm">
              <div className="font-semibold text-foreground">{closing.po.po_number}</div>
              <div className="text-muted-foreground">{closing.po.customer_name}</div>
              <div className="grid grid-cols-3 gap-2 mt-2 text-center">
                <div><div className="text-xs text-muted-foreground">Dipesan</div><div className="font-semibold">{fmtNum(closing.fulfillment.total_ordered)}</div></div>
                <div><div className="text-xs text-muted-foreground">Diterima</div><div className="font-semibold">{fmtNum(closing.fulfillment.total_received)}</div></div>
                <div><div className="text-xs text-muted-foreground">Kurang</div><div className="font-semibold text-[hsl(var(--warning))]">{fmtNum(closing.fulfillment.qty_short)} ({closing.fulfillment.qty_short_pct}%)</div></div>
                {closing.fulfillment.qc && (
                  <>
                    <div><div className="text-xs text-muted-foreground">Produksi vendor</div><div className="font-semibold text-[hsl(var(--success))]">{fmtNum(closing.fulfillment.qc.produced)}</div></div>
                    <div><div className="text-xs text-muted-foreground">Lolos QC</div><div className="font-semibold text-[hsl(var(--success))]">{fmtNum(closing.fulfillment.qc.accepted)}</div></div>
                    <div><div className="text-xs text-muted-foreground">Ditolak</div><div className="font-semibold text-[hsl(var(--destructive))]">{fmtNum(closing.fulfillment.qc.reject)} ({closing.fulfillment.qc.reject_rate_pct}%)</div></div>
                    <div><div className="text-xs text-muted-foreground">Rework belum selesai</div><div className="font-semibold text-[hsl(var(--warning))]">{fmtNum(closing.fulfillment.qc.rework_open)}</div></div>
                    <div><div className="text-xs text-muted-foreground">Dibuang (scrap)</div><div className="font-semibold text-foreground">{fmtNum(closing.fulfillment.qc.scrap)}</div></div>
                  </>
                )}
              </div>
            </div>

            <Notice tone="warning" icon={AlertTriangle} className="text-xs">
              PO akan berstatus <b>Closed Short</b> dan tidak bisa diproses lagi. Jika invoice AR sudah
              di-<i>issue</i>, sistem membuat <b>Credit Note draft</b> otomatis.
            </Notice>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Alasan penutupan *</label>
              <SmartNativeSelect
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                data-testid="po-close-short-reason"
                className="w-full px-3 py-2 rounded-lg border border-border bg-card text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
              >
                <option value="">— pilih alasan —</option>
                {(closing.fulfillment.close_short_reasons || Object.keys(REASON_LABELS)).map((r) => (
                  <option key={r} value={r}>{REASON_LABELS[r] || r}</option>
                ))}
              </SmartNativeSelect>
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Catatan (opsional)</label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                data-testid="po-close-short-notes"
                className="w-full px-3 py-2 rounded-lg border border-border bg-card text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
                placeholder="mis. Buyer membatalkan sisa order karena musim berakhir"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setClosing(null)}>
                <XCircle className="w-4 h-4" /> Batal
              </Button>
              <Button
                onClick={submitClose}
                disabled={submitting || !reason}
                data-testid="po-close-short-submit"
              >
                {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                Konfirmasi Close Short
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

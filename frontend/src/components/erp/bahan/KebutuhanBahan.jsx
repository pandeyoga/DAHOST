/**
 * KebutuhanBahan — tab "Kebutuhan" di menu Bahan (Tahap 9, 7 Nov 2026), SAMA di Portal Produksi & Maklon.
 *
 * Daftar PO portal ini → rincian kebutuhan bahan satu PO dibuka di halaman (DetailPanel).
 * Angkanya SATU sumber di server (`GET /api/rahaza/material-requirements/po/{id}` →
 * `routes.rahaza_material_requirements.po_material_need`):
 *   · PO internal: BOM produk × qty PO lewat `material_issue_engine.bom_need_for_lines` — hitungan yang
 *     sama dengan kiriman ke CMT yang mengurangi stok (dulu layar ini menghitung BOM × qty sendiri).
 *   · PO maklon: rencana bahan & aksesoris PO (`po_accessories`), sama dengan layar PO.
 * Sudah keluar, sisa, tersedia di gudang, dan kurang dihitung di server; layar hanya menampilkan.
 *
 * Pengganti layar lama "Kebutuhan Material" (`prod-material-requirements`, mode PO + mode manual model×ukuran).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ClipboardList, Download, Info, Loader2, RefreshCw, Search, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { DetailPanel } from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { apiGet } from '../../../lib/api';
import { portalBusinessType, portalQuery } from '@/lib/portalScope';
import { formatDateID } from '@/lib/format';
import { poStatusLabel, poStatusTone } from '@/lib/poStatus';

const CLOSED = ['Completed', 'Closed', 'Closed Short', 'Cancelled', 'cancelled'];
const fmtQty = (v) => {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString('id-ID', { maximumFractionDigits: 3 }) : '—';
};
const fmtRp = (v) => `Rp ${Math.round(Number(v || 0)).toLocaleString('id-ID')}`;
const STATUS_LINE = {
  shortage: ['Kurang', 'danger'], ok: ['Cukup', 'success'], unlinked: ['Belum tertaut master', 'warning'],
  client: ['Disediakan klien', 'muted'],
};

export default function KebutuhanBahan({ portalId }) {
  const businessType = portalBusinessType(portalId);
  const [pos, setPos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [scope, setScope] = useState('open');
  const [detail, setDetail] = useState(null);     // {po, loading} | hasil po_material_need

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet(`/production-pos${portalQuery(businessType)}`);
      setPos((Array.isArray(data) ? data : (data?.items || [])).filter((p) => !['Cancelled', 'cancelled'].includes(p.status)));
    } catch (e) {
      toast.error(`Gagal memuat PO: ${e.message || e}`);
      setPos([]);
    } finally { setLoading(false); }
  }, [businessType]);
  useEffect(() => { load(); }, [load]);

  const openNeed = async (po) => {
    setDetail({ po, loading: true });
    try {
      setDetail(await apiGet(`/rahaza/material-requirements/po/${po.id}`));
    } catch (e) {
      toast.error(`Gagal menghitung kebutuhan: ${e.message || e}`);
      setDetail(null);
    }
  };

  const counts = useMemo(() => ({ open: pos.filter((p) => !CLOSED.includes(p.status)).length, all: pos.length }), [pos]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return pos.filter((p) => (scope === 'all' || !CLOSED.includes(p.status))
      && (!q || [p.po_number, p.customer_name, p.vendor_name].some((v) => String(v || '').toLowerCase().includes(q))));
  }, [pos, scope, search]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);

  return (
    <PageLayout
      testId="bahan-kebutuhan"
      title="Kebutuhan bahan"
      subtitle="Bahan dan aksesoris yang dibutuhkan tiap PO, yang sudah keluar, dan yang masih kurang di gudang."
      filters={<>
        <div className="relative w-72 max-w-full">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <GlassInput value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari no. PO / klien / CMT…"
            className="pl-9 h-9" data-testid="kebutuhan-search" />
        </div>
        <FilterChips value={scope} onChange={setScope} testId="kebutuhan-scope" ariaLabel="Penyaring PO" hideWhenEmpty={false}
          options={[{ key: 'open', label: 'Berjalan', count: counts.open }, { key: 'all', label: 'Semua', count: counts.all }]} />
      </>}
      tools={<Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="kebutuhan-refresh">
        <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
      </Button>}
      detail={detail && <NeedPanel detail={detail} onClose={() => setDetail(null)} />}
      footer={filtered.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading && !pos.length ? (
          <div className="p-4 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin inline mr-2" />Memuat…</div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={ClipboardList} title="Tidak ada PO pada penyaring ini" description="Pilih penyaring lain atau ubah kata pencarian." />
        ) : (
          <Table data-testid="kebutuhan-po-table">
            <TableHeader><TableRow>
              <TableHead>No. PO</TableHead><TableHead>Klien</TableHead><TableHead>Vendor CMT</TableHead>
              <TableHead className="text-right">Qty</TableHead><TableHead>Tanggal</TableHead><TableHead>Status</TableHead>
              <TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((p) => (
                <TableRow key={p.id} data-testid={`kebutuhan-po-${p.po_number}`}
                  className={detail?.po?.id === p.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                  <TableCell className="whitespace-nowrap">
                    <Button variant="link" size="sm" className="h-auto p-0 font-semibold" onClick={() => openNeed(p)}>{p.po_number}</Button>
                  </TableCell>
                  <TableCell>{p.customer_name || '—'}</TableCell>
                  <TableCell>{p.vendor_name || '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtQty(p.total_qty)}</TableCell>
                  <TableCell className="whitespace-nowrap">{p.po_date || p.created_at ? formatDateID(p.po_date || p.created_at) : '—'}</TableCell>
                  <TableCell><StatusBadge status={p.status} label={poStatusLabel(p.status)} tone={poStatusTone(p.status)} /></TableCell>
                  <TableCell className="text-right">
                    <Button size="sm" variant="outline" onClick={() => openNeed(p)} data-testid={`kebutuhan-open-${p.po_number}`}>Lihat kebutuhan</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
    </PageLayout>
  );
}

function NeedPanel({ detail, onClose }) {
  if (detail.loading) {
    return (
      <DetailPanel title={`Kebutuhan bahan ${detail.po?.po_number || ''}`} onClose={onClose} testId="kebutuhan-detail">
        <p className="text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin inline mr-2" />Menghitung…</p>
      </DetailPanel>
    );
  }
  const { po, rows = [], totals = {}, notes = [], source_label: sourceLabel } = detail;
  const exportCSV = () => {
    const head = ['Jenis', 'Kode', 'Nama', 'Satuan', 'Dibutuhkan', 'Sudah keluar', 'Sisa', 'Tersedia', 'Kurang', 'Perkiraan nilai'];
    const esc = (v) => { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const body = rows.map((r) => [r.kind_label, r.code, r.name, r.unit, r.qty_required, r.issued, r.remaining,
      r.available ?? '', r.shortage ?? '', r.value_estimate].map(esc).join(','));
    const url = URL.createObjectURL(new Blob([`﻿${[head.join(','), ...body].join('\n')}`], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `kebutuhan-bahan-${po.po_number || 'po'}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <DetailPanel testId="kebutuhan-detail" onClose={onClose} title={`Kebutuhan bahan ${po.po_number}`}
      description={`${po.customer_name || (po.business_type === 'internal' ? 'Internal' : '—')} · ${fmtQty(po.total_qty)} pcs · sumber: ${sourceLabel}`}
      actions={<Button variant="outline" onClick={exportCSV} disabled={!rows.length} data-testid="kebutuhan-export-csv">
        <Download className="w-4 h-4" />Unduh CSV
      </Button>}>
      <p className="text-sm text-muted-foreground" data-testid="kebutuhan-summary">
        {totals.lines || 0} baris bahan · <span className={totals.shortage_lines ? 'text-[hsl(var(--danger-text))] font-medium' : ''}>{totals.shortage_lines || 0} kurang</span>
        {totals.unlinked_lines ? ` · ${totals.unlinked_lines} belum tertaut master` : ''}
        {totals.client_lines ? ` · ${totals.client_lines} disediakan klien` : ''}
        {Number(totals.value_estimate || 0) > 0 && <> · perkiraan nilai <span className="tabular-nums text-foreground">{fmtRp(totals.value_estimate)}</span></>}
      </p>
      {notes.length > 0 && (
        <Notice tone="warning" icon={AlertTriangle} testId="kebutuhan-notes" title="Perlu diperiksa">
          <ul className="list-disc pl-4 space-y-0.5">{notes.slice(0, 8).map((n, i) => <li key={i}>{n}</li>)}</ul>
        </Notice>
      )}
      {rows.length === 0 ? (
        <EmptyState icon={Info} title="Belum ada kebutuhan bahan untuk PO ini"
          description={po.business_type === 'internal' ? 'Pastikan produk di PO punya BOM aktif untuk warna dan ukurannya.'
            : 'Isi rencana bahan & aksesoris di form PO.'} />
      ) : (
        <div className="overflow-x-auto">
          <Table data-testid="kebutuhan-table">
            <TableHeader><TableRow>
              <TableHead>Jenis</TableHead><TableHead>Kode</TableHead><TableHead>Nama</TableHead><TableHead>Satuan</TableHead>
              <TableHead className="text-right">Dibutuhkan</TableHead><TableHead className="text-right">Sudah keluar</TableHead>
              <TableHead className="text-right">Sisa</TableHead><TableHead className="text-right">Tersedia</TableHead>
              <TableHead className="text-right">Kurang</TableHead><TableHead>Keterangan</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {rows.map((r, i) => {
                const [label, tone] = STATUS_LINE[r.status] || [r.status, 'muted'];
                return (
                  <TableRow key={`${r.code}-${i}`} data-testid={`kebutuhan-row-${r.code || i}`}>
                    <TableCell className="whitespace-nowrap">{r.kind_label}</TableCell>
                    <TableCell className="whitespace-nowrap">{r.code || '—'}</TableCell>
                    <TableCell>{r.name}</TableCell>
                    <TableCell>{r.unit || '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtQty(r.qty_required)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtQty(r.issued)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtQty(r.remaining)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtQty(r.available)}</TableCell>
                    <TableCell className="text-right tabular-nums" data-testid={`kebutuhan-shortage-${r.code || i}`}>
                      {r.shortage ? <span className="font-medium text-[hsl(var(--danger-text))]">{fmtQty(r.shortage)}</span> : fmtQty(r.shortage)}
                    </TableCell>
                    <TableCell><StatusBadge status={r.status} label={label} tone={tone} /></TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        {po.business_type === 'internal'
          ? 'Dihitung dari BOM produk × qty PO — angka yang sama dipakai saat kirim ke CMT mengurangi stok.'
          : 'Dari rencana bahan & aksesoris PO. Baris yang disediakan klien tidak mengurangi stok DA.'}
      </p>
    </DetailPanel>
  );
}

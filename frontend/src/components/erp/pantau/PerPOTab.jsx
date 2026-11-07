/**
 * Pantau Produksi › Per PO — tabel PO; buka baris (RowDetail) untuk seri → SKU (ukuran/warna) dengan
 * angka per tahap. Cari PO, vendor, seri, atau SKU; saring status (Selesai = LOLOS QC ≥ dipesan, bukan
 * sekadar diproduksi). Pengganti pohon kartu 4 tingkat Production Jobs.
 */
import { Fragment, useEffect, useState } from 'react';
import { AlertCircle, ClipboardList } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice } from '../moduleAtoms';
import { formatDateID } from '@/lib/format';
import {
  Badge, LoadingRows, RISK_META, RefreshButton, STATE_META, ScopeChips, SearchBox, Section, n, poStatusLabel,
  portalBusinessType, useApi,
} from './pantauShared';

function useDebounced(value, ms = 350) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

export default function PerPOTab(props) {
  const bt = portalBusinessType(props);
  const maklon = bt === 'maklon';
  const [scope, setScope] = useState('running');
  const [state, setState] = useState('');
  const [search, setSearch] = useState('');
  const q = useDebounced(search.trim());
  const [open, setOpen] = useState('');
  const path = `/pantau/po?business_type=${bt}&scope=${scope}${state ? `&status=${state}` : ''}${q ? `&search=${encodeURIComponent(q)}` : ''}`;
  const { data, loading, error, reload } = useApi(path);
  const rows = data?.rows || [];
  const c = data?.counts || {};
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);
  const COLS = maklon ? 13 : 12;
  useEffect(() => { if (q && rows.length === 1) setOpen(rows[0].po_id); }, [q, rows]);

  return (
    <PageLayout
      testId="pantau-po"
      title="Per PO"
      filters={<>
        <SearchBox value={search} onChange={setSearch} placeholder="Cari PO, vendor, seri, atau SKU…" testId="pantau-po-search" />
        <FilterChips value={state} onChange={setState} testId="pantau-po-status" ariaLabel="Status PO" hideWhenEmpty={false}
          options={[{ key: '', label: 'Semua', count: Object.values(c).reduce((a, b) => a + b, 0) },
            ...Object.entries(STATE_META).map(([k, m]) => ({ key: k, label: m.label, count: c[k] || 0 }))]} />
        <ScopeChips value={scope} onChange={setScope} testId="pantau-po-scope" />
      </>}
      tools={<RefreshButton onClick={reload} loading={loading} testId="pantau-po-refresh" />}
      summary={error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
      footer={rows.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}
    >
      <Section>
        {loading && !data ? <LoadingRows /> : rows.length === 0 ? (
          <EmptyState icon={ClipboardList} title={q || state ? 'Tidak ada PO yang cocok' : 'Belum ada PO berjalan'}
            description={q || state ? 'Ubah kata kunci atau status.' : 'PO yang dibuat di menu PO akan muncul di sini.'} />
        ) : (
          <Table data-testid="pantau-po-table">
            <TableHeader><TableRow>
              <TableHead className="w-10" /><TableHead>PO</TableHead><TableHead>Vendor CMT</TableHead><TableHead>Batas kirim</TableHead>
              <TableHead className="text-right">Dipesan</TableHead><TableHead className="text-right">Potongan dikirim</TableHead>
              <TableHead className="text-right">Diterima CMT</TableHead><TableHead className="text-right">Diproduksi</TableHead>
              <TableHead className="text-right">Di CMT</TableHead><TableHead className="text-right">Lolos QC</TableHead>
              <TableHead className="text-right">{maklon ? 'Dikirim ke klien' : 'Diserahkan ke gudang'}</TableHead>
              {maklon && <TableHead className="text-right">Diterima klien</TableHead>}
              <TableHead>Status</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((r) => {
                const isOpen = open === r.po_id;
                return (
                  <Fragment key={r.po_id}>
                    <TableRow data-testid={`pantau-po-row-${r.po_number}`}>
                      <TableCell><RowToggle open={isOpen} onClick={() => setOpen(isOpen ? '' : r.po_id)} label="Lihat seri dan SKU" testId={`pantau-po-toggle-${r.po_number}`} /></TableCell>
                      <TableCell className="font-medium whitespace-nowrap">{r.po_number}
                        <div className="text-[11px] text-muted-foreground">{r.customer_name || '—'} · {poStatusLabel(r.status)}</div></TableCell>
                      <TableCell>{r.vendor_name || '—'}</TableCell>
                      <TableCell className="whitespace-nowrap">{r.deadline ? formatDateID(r.deadline) : '—'}
                        {(r.risk === 'telat' || r.risk === 'berisiko') && <div><Badge meta={RISK_META[r.risk]} /></div>}</TableCell>
                      <TableCell className="text-right tabular-nums" data-testid="pantau-po-ordered">{n(r.ordered)}</TableCell>
                      <TableCell className="text-right tabular-nums" data-testid="pantau-po-sent">{n(r.sent_cmt)}{r.sent_extra ? <span className="text-xs text-muted-foreground"> +{n(r.sent_extra)}</span> : null}</TableCell>
                      <TableCell className="text-right tabular-nums" data-testid="pantau-po-received">{n(r.material_received)}{r.material_missing ? <span className="text-xs text-[hsl(var(--destructive))]"> −{n(r.material_missing)}</span> : null}</TableCell>
                      <TableCell className="text-right tabular-nums" data-testid="pantau-po-produced">{n(r.produced)}</TableCell>
                      <TableCell className="text-right tabular-nums" data-testid="pantau-po-dicmt">{n(r.di_cmt)}</TableCell>
                      <TableCell className="text-right tabular-nums" data-testid="pantau-po-accepted">{n(r.accepted)}{r.reject ? <span className="text-xs text-muted-foreground"> · ditolak {n(r.reject)}</span> : null}</TableCell>
                      <TableCell className="text-right tabular-nums" data-testid="pantau-po-dispatched">{n(r.dispatched)}</TableCell>
                      {maklon && <TableCell className="text-right tabular-nums" data-testid="pantau-po-final">{n(r.received_confirmed)}
                        {r.pending_confirm ? <div className="text-[11px] text-[hsl(var(--warning))]">{n(r.pending_confirm)} belum dikonfirmasi</div> : null}</TableCell>}
                      <TableCell><Badge meta={STATE_META[r.state]} testId="pantau-po-state" /></TableCell>
                    </TableRow>
                    {isOpen && (
                      <RowDetail colSpan={COLS} testId={`pantau-po-detail-${r.po_number}`}>
                        <PoLines lines={r.lines} maklon={maklon} />
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Section>
    </PageLayout>
  );
}

function PoLines({ lines, maklon }) {
  if (!lines?.length) return <p className="text-sm text-muted-foreground">PO ini belum punya baris barang.</p>;
  return (
    <Table data-testid="pantau-po-lines">
      <TableHeader><TableRow>
        <TableHead>Seri</TableHead><TableHead>SKU</TableHead><TableHead>Ukuran</TableHead><TableHead>Warna</TableHead>
        <TableHead className="text-right">Dipesan</TableHead><TableHead className="text-right">Ke CMT</TableHead>
        <TableHead className="text-right">Diterima CMT</TableHead><TableHead className="text-right">Diproduksi</TableHead>
        <TableHead className="text-right">Sedang QC</TableHead><TableHead className="text-right">Lolos QC</TableHead>
        <TableHead className="text-right">Ditolak QC</TableHead>
        <TableHead className="text-right">{maklon ? 'Dikirim' : 'Diserahkan'}</TableHead>
        {maklon && <TableHead className="text-right">Diterima klien</TableHead>}
        <TableHead>Status</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {lines.map((l) => (
          <TableRow key={l.po_item_id} data-testid={`pantau-line-${l.sku}-${l.size}`}>
            <TableCell className="text-xs whitespace-nowrap">{l.serial_number || '—'}</TableCell>
            <TableCell className="whitespace-nowrap">{l.sku}<div className="text-[11px] text-muted-foreground">{l.product_name}</div></TableCell>
            <TableCell>{l.size || '—'}</TableCell>
            <TableCell>{l.color || '—'}</TableCell>
            <TableCell className="text-right tabular-nums">{n(l.ordered)}</TableCell>
            <TableCell className="text-right tabular-nums">{n(l.sent_cmt)}{l.sent_extra ? <span className="text-xs text-muted-foreground"> +{n(l.sent_extra)}</span> : null}</TableCell>
            <TableCell className="text-right tabular-nums">{l.material_uninspected && !l.material_received ? <span className="text-xs text-muted-foreground">belum diperiksa</span> : n(l.material_received)}
              {l.material_missing ? <span className="text-xs text-[hsl(var(--destructive))]"> −{n(l.material_missing)}</span> : null}</TableCell>
            <TableCell className="text-right tabular-nums">{n(l.produced)}</TableCell>
            <TableCell className="text-right tabular-nums">{n(l.in_qc)}</TableCell>
            <TableCell className="text-right tabular-nums">{n(l.accepted)}</TableCell>
            <TableCell className="text-right tabular-nums">{n(l.reject)}{l.reject_open ? <span className="text-xs text-[hsl(var(--warning))]"> ({n(l.reject_open)} terbuka)</span> : null}</TableCell>
            <TableCell className="text-right tabular-nums">{n(l.dispatched)}</TableCell>
            {maklon && <TableCell className="text-right tabular-nums">{n(l.received_confirmed)}{l.pending_confirm ? <span className="text-xs text-[hsl(var(--warning))]"> ({n(l.pending_confirm)} belum dikonfirmasi)</span> : null}</TableCell>}
            <TableCell><Badge meta={STATE_META[l.state]} /></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

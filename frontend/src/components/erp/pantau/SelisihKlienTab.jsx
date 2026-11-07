/**
 * Laporan Selisih › Terima klien (PO maklon) — dikirim ke klien vs DITERIMA klien per PO. Baris yang belum
 * dikonfirmasi klien ditampilkan "belum dikonfirmasi", BUKAN dianggap diterima penuh (perbaikan Tahap 9).
 * PO internal diserahkan ke gudang sendiri, tidak dikonfirmasi klien.
 */
import { Fragment, useState } from 'react';
import { AlertCircle, PackageCheck } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import { Badge, LoadingRows, RefreshButton, Section, n, useApi } from './pantauShared';
import { SelisihFilters, useSelisihFilter } from './selisihShared';

const STATUS_META = {
  belum_dikonfirmasi: { label: 'Belum dikonfirmasi', tone: 'warning' },
  selisih: { label: 'Ada selisih', tone: 'danger' },
  sesuai: { label: 'Sesuai', tone: 'success' },
};

export default function SelisihKlienTab() {
  const f = useSelisihFilter();
  const maklon = f.bt === 'maklon';
  const { data, loading, error, reload } = useApi(maklon ? `/pantau/selisih/klien?${f.query}` : null);
  const rows = data?.rows || [];
  const sm = data?.summary || {};
  const [open, setOpen] = useState('');
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);

  return (
    <PageLayout
      testId="selisih-klien"
      title="Terima klien"
      filters={<SelisihFilters testId="selisih-klien-filter" />}
      tools={maklon && <RefreshButton onClick={reload} loading={loading} testId="selisih-klien-refresh" />}
      summary={<>
        {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
        {maklon && rows.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="selisih-klien-kpi">
            <StatTile label="Dikirim ke klien" value={n(sm.total_shipped)} sub="pcs" />
            <StatTile label="Diterima klien" value={n(sm.total_received)} sub="pcs, sudah dikonfirmasi" testId="kpi-klien-diterima" />
            <StatTile label="Belum dikonfirmasi" value={n(sm.total_unconfirmed)} sub="pcs, belum dihitung diterima" accent={sm.total_unconfirmed ? 'warning' : 'muted'} testId="kpi-klien-belum" />
            <StatTile label="Kurang diterima" value={n(sm.total_variance)} sub={`${n(sm.qty_short_open)} pcs selisih masih terbuka`} accent={sm.total_variance ? 'danger' : 'muted'} />
          </div>
        )}
      </>}
      footer={rows.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}
    >
      <Section>
        {!maklon ? (
          <EmptyState icon={PackageCheck} title="Hanya untuk PO maklon" description="PO internal diserahkan ke gudang DA sendiri, tidak dikonfirmasi klien. Pilih portal PO maklon." />
        ) : loading && !data ? <LoadingRows /> : rows.length === 0 ? (
          <EmptyState icon={PackageCheck} title="Belum ada kiriman ke klien" description="Kiriman dari menu Kirim hasil akan muncul di sini setelah dibuat." />
        ) : (
          <Table data-testid="selisih-klien-table">
            <TableHeader><TableRow>
              <TableHead className="w-10" /><TableHead>PO</TableHead><TableHead>Klien</TableHead>
              <TableHead className="text-right">Dikirim</TableHead><TableHead className="text-right">Diterima</TableHead>
              <TableHead className="text-right">Belum dikonfirmasi</TableHead><TableHead className="text-right">Kurang diterima</TableHead>
              <TableHead className="text-right">Selisih terbuka</TableHead><TableHead>Status</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((r) => {
                const isOpen = open === r.po_id;
                return (
                  <Fragment key={r.po_id}>
                    <TableRow data-testid={`selisih-klien-row-${r.po_number}`}>
                      <TableCell><RowToggle open={isOpen} onClick={() => setOpen(isOpen ? '' : r.po_id)} testId={`selisih-klien-toggle-${r.po_number}`} /></TableCell>
                      <TableCell className="font-medium whitespace-nowrap">{r.po_number}</TableCell>
                      <TableCell>{r.customer_name || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(r.total_shipped)}</TableCell>
                      <TableCell className="text-right tabular-nums" data-testid="selisih-klien-received">{n(r.total_received)}</TableCell>
                      <TableCell className="text-right tabular-nums" data-testid="selisih-klien-unconfirmed">{n(r.total_unconfirmed)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(r.total_variance)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(r.qty_short_open)}</TableCell>
                      <TableCell><Badge meta={STATUS_META[r.status]} /></TableCell>
                    </TableRow>
                    {isOpen && (
                      <RowDetail colSpan={9}>
                        <Table>
                          <TableHeader><TableRow>
                            <TableHead>Seri</TableHead><TableHead>SKU</TableHead><TableHead>Ukuran</TableHead>
                            <TableHead className="text-right">Dikirim</TableHead><TableHead className="text-right">Diterima</TableHead>
                            <TableHead className="text-right">Belum dikonfirmasi</TableHead><TableHead className="text-right">Kurang</TableHead>
                          </TableRow></TableHeader>
                          <TableBody>
                            {r.items.map((it) => (
                              <TableRow key={it.po_item_id || it.sku}>
                                <TableCell className="text-xs">{it.serial_number || '—'}</TableCell>
                                <TableCell>{it.sku}<div className="text-[11px] text-muted-foreground">{it.product_name}</div></TableCell>
                                <TableCell>{it.size || '—'}</TableCell>
                                <TableCell className="text-right tabular-nums">{n(it.shipped)}</TableCell>
                                <TableCell className="text-right tabular-nums">{n(it.received)}</TableCell>
                                <TableCell className="text-right tabular-nums">{n(it.unconfirmed)}</TableCell>
                                <TableCell className="text-right tabular-nums">{n(it.variance)}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
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

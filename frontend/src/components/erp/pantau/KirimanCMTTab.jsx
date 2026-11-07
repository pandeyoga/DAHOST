/**
 * Pantau Produksi › Kiriman ke CMT — per surat jalan (batch) potongan DA → CMT: dikirim, diterima CMT
 * (hasil periksa bahan), kurang. Kiriman pengganti/tambahan ditandai terpisah dari kiriman normal.
 * Pengganti tab "Potongan masuk" Monitoring CMT (kini juga untuk PO internal).
 */
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Fragment, useMemo, useState } from 'react';
import { AlertCircle, Truck } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice } from '../moduleAtoms';
import { formatDateID } from '@/lib/format';
import { Badge, KIND_LABEL, LoadingRows, RefreshButton, SearchBox, Section, n, portalBusinessType, useApi } from './pantauShared';

export default function KirimanCMTTab(props) {
  const bt = portalBusinessType(props);
  const [search, setSearch] = useState('');
  const [kind, setKind] = useState('');
  const [check, setCheck] = useState('');
  const [open, setOpen] = useState('');
  const { data, loading, error, reload } = useApi(`/pantau/kiriman?business_type=${bt}`);
  const all = useMemo(() => data?.batches || [], [data]);
  const counts = useMemo(() => {
    const c = { kind: {}, belum: 0, kurang: 0 };
    all.forEach((b) => {
      c.kind[b.kind] = (c.kind[b.kind] || 0) + 1;
      if (b.total_received == null) c.belum += 1;
      if (b.total_missing) c.kurang += 1;
    });
    return c;
  }, [all]);
  const rows = useMemo(() => {
    const s = search.trim().toLowerCase();
    return all.filter((b) => {
      if (kind && b.kind !== kind) return false;
      if (check === 'belum' && b.total_received != null) return false;
      if (check === 'kurang' && !b.total_missing) return false;
      return !s || [b.shipment_number, b.delivery_note_number, b.po_number, b.vendor_name, b.customer_name]
        .some((x) => (x || '').toLowerCase().includes(s));
    });
  }, [all, search, kind, check]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);

  return (
    <PageLayout
      testId="pantau-kiriman"
      title="Kiriman ke CMT"
      filters={<>
        <SearchBox value={search} onChange={setSearch} placeholder="Cari surat jalan, PO, vendor…" testId="pantau-kiriman-search" />
        <FilterChips value={kind} onChange={setKind} testId="pantau-kiriman-kind" ariaLabel="Jenis kiriman"
          options={[{ key: '', label: 'Semua', count: all.length },
            ...Object.keys(KIND_LABEL).map((k) => ({ key: k, label: KIND_LABEL[k], count: counts.kind[k] || 0 }))
              .filter((o) => o.count)]} />
        <FilterChips value={check} onChange={setCheck} testId="pantau-kiriman-check" ariaLabel="Hasil periksa"
          options={[{ key: '', label: 'Semua periksa' }, { key: 'belum', label: 'Belum diperiksa', count: counts.belum },
            { key: 'kurang', label: 'Ada kurang', count: counts.kurang }]} hideWhenEmpty={false} />
      </>}
      tools={<><TombolUnduh namaBerkas="kiriman-ke-cmt-pantau" baris={rows} kolom={[
          { label: 'Surat jalan', nilai: (b) => b.shipment_number || '' }, { label: 'No. SJ', nilai: (b) => b.delivery_note_number || '' },
          { label: 'PO', nilai: (b) => b.po_number || '' }, { label: 'Vendor CMT', nilai: (b) => b.vendor_name || '' },
          { label: 'Tanggal', nilai: (b) => formatDateID(b.shipment_date, { fallback: '' }) }, { label: 'Jenis', nilai: (b) => KIND_LABEL[b.kind] || b.kind || '' },
          { label: 'Dikirim', nilai: (b) => Number(b.total_sent) || 0 }, { label: 'Diterima CMT', nilai: (b) => Number(b.total_received) || 0 },
          { label: 'Kurang', nilai: (b) => Number(b.total_missing) || 0 },
        ]} />
        <RefreshButton onClick={reload} loading={loading} testId="pantau-kiriman-refresh" /></>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
        {data && all.length > 0 && (
          <p className="text-sm text-muted-foreground" data-testid="pantau-kiriman-summary">
            {n(data.count)} kiriman · dikirim <b className="text-foreground tabular-nums">{n(data.total_sent)}</b> pcs ·
            diterima CMT <b className="text-foreground tabular-nums">{n(data.total_received)}</b> · kurang{' '}
            <b className={`tabular-nums ${data.total_missing ? 'text-[hsl(var(--danger-text))]' : 'text-foreground'}`}>{n(data.total_missing)}</b> ·
            {' '}{n(data.uninspected)} belum diperiksa CMT
          </p>
        )}
      </>}
      footer={rows.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}
    >
      <Section>
        {loading && !data ? <LoadingRows /> : rows.length === 0 ? (
          <EmptyState icon={Truck} title="Belum ada kiriman ke CMT" description="Kiriman potongan dari menu Kirim ke CMT akan muncul di sini." />
        ) : (
          <Table data-testid="pantau-kiriman-table">
            <TableHeader><TableRow>
              <TableHead className="w-10" /><TableHead>Surat jalan</TableHead><TableHead>PO</TableHead><TableHead>Vendor CMT</TableHead>
              <TableHead>Tanggal</TableHead><TableHead>Jenis</TableHead><TableHead className="text-right">Dikirim</TableHead>
              <TableHead className="text-right">Diterima CMT</TableHead><TableHead className="text-right">Kurang</TableHead><TableHead>Periksa</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((b) => {
                const isOpen = open === b.shipment_id;
                const checked = b.total_received != null;
                return (
                  <Fragment key={b.shipment_id}>
                    <TableRow data-testid={`pantau-kiriman-row-${b.shipment_number}`}>
                      <TableCell><RowToggle open={isOpen} onClick={() => setOpen(isOpen ? '' : b.shipment_id)} testId={`pantau-kiriman-toggle-${b.shipment_number}`} /></TableCell>
                      <TableCell className="font-medium whitespace-nowrap">{b.shipment_number || '—'}{b.delivery_note_number ? <div className="text-xs text-muted-foreground">{b.delivery_note_number}</div> : null}</TableCell>
                      <TableCell className="whitespace-nowrap">{b.po_number}<div className="text-xs text-muted-foreground">{b.customer_name}</div></TableCell>
                      <TableCell>{b.vendor_name || '—'}</TableCell>
                      <TableCell className="whitespace-nowrap">{b.shipment_date ? formatDateID(b.shipment_date) : '—'}</TableCell>
                      <TableCell>{KIND_LABEL[b.kind] || b.kind}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(b.total_sent)}</TableCell>
                      <TableCell className="text-right tabular-nums">{checked ? n(b.total_received) : '—'}</TableCell>
                      <TableCell className={`text-right tabular-nums ${b.total_missing ? 'text-[hsl(var(--danger-text))] font-semibold' : ''}`}>{checked ? n(b.total_missing) : '—'}</TableCell>
                      <TableCell><Badge meta={checked ? (b.total_missing ? { label: 'Ada kurang', tone: 'danger' } : { label: 'Sesuai', tone: 'success' }) : { label: 'Belum diperiksa', tone: 'warning' }} /></TableCell>
                    </TableRow>
                    {isOpen && (
                      <RowDetail colSpan={10} testId={`pantau-kiriman-detail-${b.shipment_number}`}>
                        <Table>
                          <TableHeader><TableRow>
                            <TableHead>Seri</TableHead><TableHead>SKU</TableHead><TableHead>Ukuran</TableHead><TableHead>Warna</TableHead>
                            <TableHead className="text-right">Dikirim</TableHead><TableHead className="text-right">Diterima</TableHead><TableHead className="text-right">Kurang</TableHead>
                          </TableRow></TableHeader>
                          <TableBody>
                            {b.items.map((it) => (
                              <TableRow key={it.vsi_id}>
                                <TableCell className="text-xs">{it.serial_number || '—'}</TableCell>
                                <TableCell>{it.sku}<div className="text-xs text-muted-foreground">{it.product_name}</div></TableCell>
                                <TableCell>{it.size || '—'}</TableCell><TableCell>{it.color || '—'}</TableCell>
                                <TableCell className="text-right tabular-nums">{n(it.qty_sent)}</TableCell>
                                <TableCell className="text-right tabular-nums">{it.inspected ? n(it.received_qty) : '—'}</TableCell>
                                <TableCell className="text-right tabular-nums">{it.inspected ? n(it.missing_qty) : '—'}</TableCell>
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

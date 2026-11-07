/**
 * Pantau Produksi › Per vendor CMT — satu baris per vendor (jumlah baris PO-nya). Buka baris (RowDetail)
 * untuk job jahit vendor itu beserta QC per job, job anak, tanda "diinput staf DA", dan PO yang belum
 * punya job (menunggu kiriman bahan). Pengganti kartu vendor di Tracking Produksi / Production Jobs.
 */
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Fragment, useMemo, useState } from 'react';
import { AlertCircle, Factory } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice } from '../moduleAtoms';
import { formatDateID } from '@/lib/format';
import {
  Badge, ENTRY_META, LoadingRows, RISK_META, RefreshButton, ScopeChips, SearchBox, Section, jobStatusLabel, n, pct,
  portalBusinessType, useApi,
} from './pantauShared';

export default function PerVendorTab(props) {
  const bt = portalBusinessType(props);
  const [scope, setScope] = useState('running');
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState('');
  const { data, loading, error, reload } = useApi(`/pantau/vendor?business_type=${bt}&scope=${scope}`);
  const rows = useMemo(() => {
    const s = search.trim().toLowerCase();
    return (data?.rows || []).filter((v) => !s || [v.vendor_name, v.vendor_code].some((x) => (x || '').toLowerCase().includes(s)));
  }, [data, search]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);
  const finalLabel = bt === 'maklon' ? 'Dikirim ke klien' : 'Diserahkan ke gudang';
  const COLS = 12;

  return (
    <PageLayout
      testId="pantau-vendor"
      title="Per vendor CMT"
      filters={<>
        <SearchBox value={search} onChange={setSearch} placeholder="Cari vendor…" testId="pantau-vendor-search" />
        <ScopeChips value={scope} onChange={setScope} testId="pantau-vendor-scope" />
      </>}
      tools={<><TombolUnduh namaBerkas="pantau-per-vendor" baris={rows} kolom={[
          { label: 'Vendor', nilai: (v) => v.vendor_name || '' }, { label: 'Kode', nilai: (v) => v.vendor_code || '' },
          { label: 'PO', nilai: (v) => Number(v.po_count) || 0 }, { label: 'Dipesan', nilai: (v) => Number(v.ordered) || 0 },
          { label: 'Potongan dikirim', nilai: (v) => Number(v.sent_cmt) || 0 }, { label: 'Diproduksi', nilai: (v) => Number(v.produced) || 0 },
          { label: 'Di CMT', nilai: (v) => Number(v.di_cmt) || 0 }, { label: 'Lolos QC', nilai: (v) => Number(v.accepted) || 0 },
          { label: 'Ditolak QC', nilai: (v) => Number(v.reject) || 0 }, { label: 'Dikirim/diserahkan', nilai: (v) => Number(v.dispatched) || 0 },
          { label: 'Ditolak (%)', nilai: (v) => Number(v.reject_rate) || 0 },
        ]} />
        <RefreshButton onClick={reload} loading={loading} testId="pantau-vendor-refresh" /></>}
      summary={error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
      footer={rows.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}
    >
      <Section>
        {loading && !data ? <LoadingRows /> : rows.length === 0 ? (
          <EmptyState icon={Factory} title="Belum ada PO di vendor CMT" description="PO yang sudah dibuat akan muncul di sini, dikelompokkan per vendor." />
        ) : (
          <Table data-testid="pantau-vendor-table">
            <TableHeader><TableRow>
              <TableHead className="w-10" /><TableHead>Vendor</TableHead><TableHead className="text-right">PO</TableHead>
              <TableHead className="text-right">Dipesan</TableHead><TableHead className="text-right">Potongan dikirim</TableHead>
              <TableHead className="text-right">Diproduksi</TableHead><TableHead className="text-right">Di CMT</TableHead>
              <TableHead className="text-right">Lolos QC</TableHead><TableHead className="text-right">Ditolak QC</TableHead>
              <TableHead className="text-right">{finalLabel}</TableHead><TableHead>Keadaan</TableHead><TableHead>Input</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((v) => {
                const key = v.vendor_id || v.vendor_name;
                const isOpen = open === key;
                return (
                  <Fragment key={key}>
                    <TableRow data-testid={`pantau-vendor-row-${v.vendor_code || v.vendor_name}`}>
                      <TableCell><RowToggle open={isOpen} onClick={() => setOpen(isOpen ? '' : key)} label="Lihat job vendor" testId={`pantau-vendor-toggle-${v.vendor_code || v.vendor_name}`} /></TableCell>
                      <TableCell className="font-medium">{v.vendor_name}{v.vendor_code ? <span className="text-xs text-muted-foreground"> · {v.vendor_code}</span> : null}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(v.po_count)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(v.ordered)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(v.sent_cmt)}{v.sent_extra ? <span className="text-xs text-muted-foreground"> +{n(v.sent_extra)}</span> : null}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(v.produced)}</TableCell>
                      <TableCell className="text-right tabular-nums font-semibold" data-testid="pantau-vendor-di-cmt">{n(v.di_cmt)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(v.accepted)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(v.reject)} <span className="text-xs text-muted-foreground">({pct(v.reject_rate)})</span></TableCell>
                      <TableCell className="text-right tabular-nums">{n(v.dispatched)}</TableCell>
                      <TableCell><Badge meta={RISK_META[v.performance]} /></TableCell>
                      <TableCell>{ENTRY_META[v.entry_source] ? <Badge meta={ENTRY_META[v.entry_source]} testId="pantau-vendor-entry" /> : <span className="text-muted-foreground">—</span>}</TableCell>
                    </TableRow>
                    {isOpen && (
                      <RowDetail colSpan={COLS} testId={`pantau-vendor-detail-${v.vendor_code || v.vendor_name}`}>
                        <VendorJobs v={v} />
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

function VendorJobs({ v }) {
  return (
    <div className="space-y-3">
      {v.entry_source === 'staff' || v.entry_source === 'mixed' ? (
        <p className="text-xs text-[hsl(var(--warning-text))]">{n(v.staff_qty)} pcs progres vendor ini diketik staf DA atas nama vendor — periksa sebelum tagihan dibuat.</p>
      ) : null}
      {v.jobs.length > 0 && (
        <Table data-testid="pantau-vendor-jobs">
          <TableHeader><TableRow>
            <TableHead>Job</TableHead><TableHead>PO</TableHead><TableHead>Seri</TableHead><TableHead>Batas kirim</TableHead>
            <TableHead className="text-right">Dipesan</TableHead><TableHead className="text-right">Diproduksi</TableHead>
            <TableHead className="text-right">Lolos QC</TableHead><TableHead className="text-right">Ditolak QC</TableHead>
            <TableHead className="text-right">Permak terbuka</TableHead><TableHead>Status</TableHead><TableHead>Input</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {v.jobs.map((j) => (
              <TableRow key={j.id}>
                <TableCell className="font-medium whitespace-nowrap">{j.job_number}
                  {j.child_jobs?.length > 0 && <div className="text-xs text-muted-foreground">+{j.child_jobs.length} job tambahan: {j.child_jobs.map((c) => c.job_number).join(', ')}</div>}
                </TableCell>
                <TableCell className="whitespace-nowrap">{j.po_number}</TableCell>
                <TableCell className="text-xs">{(j.serial_numbers || []).join(', ') || '—'}</TableCell>
                <TableCell className="whitespace-nowrap">{j.deadline ? formatDateID(j.deadline) : '—'}</TableCell>
                <TableCell className="text-right tabular-nums">{n(j.ordered || j.available)}</TableCell>
                <TableCell className="text-right tabular-nums">{n(j.produced)} <span className="text-xs text-muted-foreground">({pct(j.progress_pct)})</span></TableCell>
                <TableCell className="text-right tabular-nums">{n(j.accepted)}</TableCell>
                <TableCell className="text-right tabular-nums">{n(j.reject)}</TableCell>
                <TableCell className="text-right tabular-nums">{n(j.rework_open)}</TableCell>
                <TableCell>{jobStatusLabel(j.status)}</TableCell>
                <TableCell>{ENTRY_META[j.entry_source] ? <Badge meta={ENTRY_META[j.entry_source]} /> : <span className="text-muted-foreground">—</span>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {v.pending_pos.length > 0 && (
        <p className="text-sm" data-testid="pantau-vendor-pending">
          <span className="font-medium">Belum punya job (menunggu kiriman bahan):</span>{' '}
          {v.pending_pos.map((p) => `${p.po_number} (${n(p.ordered)} pcs${p.deadline ? `, batas ${formatDateID(p.deadline)}` : ''})`).join(' · ')}
        </p>
      )}
      {v.jobs.length === 0 && v.pending_pos.length === 0 && (
        <p className="text-sm text-muted-foreground">Vendor ini belum punya job jahit pada cakupan ini.</p>
      )}
    </div>
  );
}

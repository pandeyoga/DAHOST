/**
 * Pantau Produksi › Kejar CMT — papan aging per PO: target CMT = batas kirim − buffer, sisa di CMT, kali
 * setor, hari di CMT. Kini untuk PO internal DAN maklon (dulu hanya maklon). Sumber: /api/pantau/kejar
 * (services.cmt_kejar, angka qty dari core.pantau_produksi).
 */
import { Fragment, useState } from 'react';
import { AlertCircle, ListChecks } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice } from '../moduleAtoms';
import { formatDateID, formatRupiah } from '@/lib/format';
import {
  BUCKET_META, Badge, KIND_LABEL, LoadingRows, RefreshButton, ScopeChips, Section, n, portalBusinessType, useApi,
} from './pantauShared';

export default function KejarCMTTab(props) {
  const bt = portalBusinessType(props);
  const [scope, setScope] = useState('running');
  const [bucket, setBucket] = useState('');
  const [open, setOpen] = useState('');
  const { data, loading, error, reload } = useApi(`/pantau/kejar?business_type=${bt}&scope=${scope}${bucket ? `&bucket=${bucket}` : ''}`);
  const rows = data?.rows || [];
  const bc = data?.bucket_counts || {};
  const cfg = data?.config || {};
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);

  return (
    <PageLayout
      testId="pantau-kejar"
      title="Kejar CMT"
      filters={<>
        <FilterChips value={bucket} onChange={setBucket} testId="pantau-kejar-bucket" ariaLabel="Keadaan kejar"
          options={[{ key: '', label: 'Semua', count: data?.total || 0 },
            ...Object.entries(BUCKET_META).map(([k, m]) => ({ key: k, label: m.label, count: bc[k] || 0 }))]} />
        <ScopeChips value={scope} onChange={setScope} testId="pantau-kejar-scope" />
      </>}
      tools={<RefreshButton onClick={reload} loading={loading} testId="pantau-kejar-refresh" />}
      summary={<>
        {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
        {data && <p className="text-xs text-muted-foreground">Target CMT = batas kirim − {n(cfg.buffer_days)} hari. Telat = lewat target lebih dari {n(cfg.late_grace_days)} hari.</p>}
      </>}
      footer={rows.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}
    >
      <Section>
        {loading && !data ? <LoadingRows /> : rows.length === 0 ? (
          <EmptyState icon={ListChecks} title="Tidak ada PO yang perlu dikejar" description="PO yang masih punya potongan di CMT akan muncul di sini." />
        ) : (
          <Table data-testid="pantau-kejar-table">
            <TableHeader><TableRow>
              <TableHead className="w-10" /><TableHead>PO</TableHead><TableHead>Vendor CMT</TableHead><TableHead>Keadaan</TableHead>
              <TableHead>Target CMT</TableHead><TableHead>Batas kirim</TableHead>
              <TableHead className="text-right">Dipesan</TableHead><TableHead className="text-right">Potongan ke CMT</TableHead>
              <TableHead className="text-right">Di CMT</TableHead><TableHead className="text-right">Sedang QC</TableHead>
              <TableHead className="text-right">Disetor</TableHead><TableHead className="text-right">Kali setor</TableHead>
              <TableHead className="text-right">Hari di CMT</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((r) => {
                const isOpen = open === r.po_id;
                return (
                  <Fragment key={r.po_id}>
                    <TableRow data-testid={`pantau-kejar-row-${r.po_number}`}>
                      <TableCell><RowToggle open={isOpen} onClick={() => setOpen(isOpen ? '' : r.po_id)} testId={`pantau-kejar-toggle-${r.po_number}`} /></TableCell>
                      <TableCell className="font-medium whitespace-nowrap">{r.po_number}<div className="text-xs text-muted-foreground">{r.customer_name || '—'}</div></TableCell>
                      <TableCell>{r.vendor_name || '—'}</TableCell>
                      <TableCell><Badge meta={BUCKET_META[r.bucket]} />
                        {r.bucket === 'telat' || r.bucket === 'jatuh_tempo' ? <div className="text-xs text-[hsl(var(--danger-text))]">lewat {n(r.overdue_days)} hari</div> : null}</TableCell>
                      <TableCell className="whitespace-nowrap">{r.target_cmt_date ? formatDateID(r.target_cmt_date) : '—'}</TableCell>
                      <TableCell className="whitespace-nowrap">{r.delivery_deadline || r.internal_deadline ? formatDateID(r.delivery_deadline || r.internal_deadline) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(r.qty_ordered)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(r.qty_sent_cmt)}</TableCell>
                      <TableCell className="text-right tabular-nums font-semibold" data-testid="pantau-kejar-dicmt">{n(r.qty_outstanding_cmt)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(r.qty_in_qc)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(r.qty_returned)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(r.kali_setor)}×</TableCell>
                      <TableCell className="text-right tabular-nums">{r.days_at_cmt == null ? '—' : n(r.days_at_cmt)}</TableCell>
                    </TableRow>
                    {isOpen && (
                      <RowDetail colSpan={13} testId={`pantau-kejar-detail-${r.po_number}`}>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-1 text-sm">
                          <Fact label="Belum dikirim ke CMT" v={n(r.qty_not_sent_cmt)} />
                          <Fact label="Lolos QC" v={n(r.qty_accepted)} />
                          <Fact label="Ditolak QC" v={`${n(r.qty_reject)} (berhasil ${n(r.qty_repaired)} · dibuang ${n(r.qty_scrap)} · belum jelas ${n(r.qty_reject_open)})`} />
                          <Fact label="Klaim CMT belum sampai" v={n(r.qty_short_open)} />
                          <Fact label={bt === 'maklon' ? 'Sudah dikirim ke klien' : 'Sudah diserahkan ke gudang'} v={n(r.qty_shipped_buyer)} />
                          <Fact label="Sisa bisa dikirim" v={n(r.qty_shippable_buyer)} />
                          <Fact label="Ongkos jahit terhitung" v={formatRupiah(r.ongkos_jahit_terhitung)} />
                          <Fact label="Kiriman di luar pesanan" v={r.qty_sent_extra
                            ? Object.entries(r.qty_sent_extra_by_type || {}).map(([k, q]) => `${KIND_LABEL[k] || k} ${n(q)}`).join(' · ')
                            : '0'} />
                          <Fact label="Kirim pertama" v={r.earliest_dispatch_date ? formatDateID(r.earliest_dispatch_date) : '—'} />
                        </div>
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

function Fact({ label, v }) {
  return (
    <div className="flex justify-between gap-3 border-b border-[var(--glass-border)] py-1">
      <span className="text-muted-foreground">{label}</span><span className="tabular-nums text-right">{v}</span>
    </div>
  );
}

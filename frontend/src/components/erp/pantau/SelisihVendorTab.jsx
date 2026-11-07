/**
 * Laporan Selisih › Laporan vendor — selisih produksi yang DIISI VENDOR (Portal Vendor), qty dari catatan
 * produksi job. Admin menandai diketahui/selesai. Tidak dijurnal: kelebihan barang sudah masuk stok lewat
 * Terima & QC, dan sisa WIP PO ditutup saat Tutup PO.
 */
import { Fragment, useState } from 'react';
import { AlertCircle, FileWarning, Info } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassInput } from '@/components/ui/glass';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import Modal from '../Modal';
import { formatDateID } from '@/lib/format';
import { apiPut } from '../../../lib/api';
import { Badge, LoadingRows, RefreshButton, Section, n, useApi } from './pantauShared';
import { SelisihFilters, useSelisihFilter } from './selisihShared';

const STATUS_META = {
  Reported: { label: 'Dilaporkan', tone: 'warning' },
  Acknowledged: { label: 'Diketahui', tone: 'info' },
  Resolved: { label: 'Selesai', tone: 'success' },
};
const TYPE_LABEL = { OVERPRODUCTION: 'Lebih produksi', UNDERPRODUCTION: 'Kurang produksi' };

export default function SelisihVendorTab() {
  const f = useSelisihFilter();
  const { data, loading, error, reload } = useApi(`/pantau/selisih/vendor?${f.query}`);
  const rows = data?.rows || [];
  const sm = data?.summary || {};
  const [open, setOpen] = useState('');
  const [editing, setEditing] = useState(null);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);

  return (
    <PageLayout
      testId="selisih-vendor"
      title="Laporan vendor"
      filters={<SelisihFilters testId="selisih-vendor-filter" />}
      tools={<RefreshButton onClick={reload} loading={loading} testId="selisih-vendor-refresh" />}
      summary={<>
        {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
        {rows.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatTile label="Laporan" value={n(data.count)} sub={`${n(sm.open)} belum selesai`} />
            <StatTile label="Lebih produksi" value={n(sm.over_qty)} sub={`${n(sm.over_count)} laporan`} accent={sm.over_qty ? 'warning' : 'muted'} />
            <StatTile label="Kurang produksi" value={n(sm.under_qty)} sub={`${n(sm.under_count)} laporan`} accent={sm.under_qty ? 'danger' : 'muted'} />
          </div>
        )}
        <Notice tone="info" icon={Info} testId="selisih-vendor-no-gl">Laporan ini tidak dijurnal. Kelebihan barang sudah masuk stok dan buku lewat Terima & QC; sisa barang dalam proses PO ditutup otomatis saat Tutup PO.</Notice>
      </>}
      footer={rows.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}
    >
      <Section>
        {loading && !data ? <LoadingRows /> : rows.length === 0 ? (
          <EmptyState icon={FileWarning} title="Belum ada laporan dari vendor" description="Vendor melaporkan selisih produksi lewat Portal Vendor; selisih otomatis ada di tab Per baris PO." />
        ) : (
          <Table data-testid="selisih-vendor-table">
            <TableHeader><TableRow>
              <TableHead className="w-10" /><TableHead>Tanggal</TableHead><TableHead>Vendor</TableHead><TableHead>PO · job</TableHead>
              <TableHead>Jenis</TableHead><TableHead className="text-right">Pcs</TableHead><TableHead>Alasan</TableHead>
              <TableHead>Status</TableHead><TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((v) => {
                const isOpen = open === v.id;
                return (
                  <Fragment key={v.id}>
                    <TableRow data-testid={`selisih-vendor-row-${v.job_number}`}>
                      <TableCell><RowToggle open={isOpen} onClick={() => setOpen(isOpen ? '' : v.id)} /></TableCell>
                      <TableCell className="whitespace-nowrap">{formatDateID(v.created_at)}</TableCell>
                      <TableCell>{v.vendor_name || '—'}</TableCell>
                      <TableCell className="whitespace-nowrap">{v.po_number}<div className="text-[11px] text-muted-foreground">{v.job_number}</div></TableCell>
                      <TableCell>{TYPE_LABEL[v.variance_type] || v.variance_type}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(v.total_variance_qty)}</TableCell>
                      <TableCell className="text-xs">{v.reason || '—'}</TableCell>
                      <TableCell><Badge meta={STATUS_META[v.status || 'Reported']} /></TableCell>
                      <TableCell className="text-right">
                        {(v.allowed_next || []).length > 0 && (
                          <Button variant="outline" size="sm" onClick={() => setEditing(v)} data-testid={`selisih-vendor-status-${v.job_number}`}>Ubah status</Button>
                        )}
                      </TableCell>
                    </TableRow>
                    {isOpen && (
                      <RowDetail colSpan={9}>
                        <Table>
                          <TableHeader><TableRow>
                            <TableHead>SKU</TableHead><TableHead>Ukuran</TableHead><TableHead>Warna</TableHead>
                            <TableHead className="text-right">Dipesan</TableHead><TableHead className="text-right">Diproduksi</TableHead><TableHead className="text-right">Selisih</TableHead>
                          </TableRow></TableHeader>
                          <TableBody>
                            {(v.items || []).map((it, i) => (
                              <TableRow key={it.job_item_id || i}>
                                <TableCell>{it.sku}<div className="text-[11px] text-muted-foreground">{it.product_name}</div></TableCell>
                                <TableCell>{it.size || '—'}</TableCell><TableCell>{it.color || '—'}</TableCell>
                                <TableCell className="text-right tabular-nums">{n(it.ordered_qty)}</TableCell>
                                <TableCell className="text-right tabular-nums">{n(it.produced_qty)}</TableCell>
                                <TableCell className="text-right tabular-nums">{n(it.variance_qty)}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                        {v.admin_notes ? <p className="text-xs text-muted-foreground mt-2">Catatan admin: {v.admin_notes}</p> : null}
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Section>
      {editing && <StatusForm v={editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); reload(); }} />}
    </PageLayout>
  );
}

function StatusForm({ v, onClose, onDone }) {
  const [status, setStatus] = useState(v.allowed_next?.[0] || '');
  const [notes, setNotes] = useState(v.admin_notes || '');
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      await apiPut(`/production-variances/${v.id}`, { status, admin_notes: notes });
      toast.success(`Status laporan ${v.job_number} diubah menjadi ${STATUS_META[status]?.label || status}`);
      onDone();
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };
  return (
    <Modal onClose={onClose} title="Ubah status laporan vendor" size="sm" description={`${v.po_number} · ${v.job_number}`}>
      <div className="space-y-3">
        <div><label className="text-xs text-muted-foreground">Status baru</label>
          <SmartNativeSelect value={status} onChange={(e) => setStatus(e.target.value)} searchable={false} className="h-9 w-full" aria-label="Status baru" data-testid="selisih-vendor-status-select">
            {(v.allowed_next || []).map((s) => <option key={s} value={s}>{STATUS_META[s]?.label || s}</option>)}
          </SmartNativeSelect></div>
        <div><label className="text-xs text-muted-foreground" htmlFor="selisih-admin-notes">Catatan</label>
          <GlassInput id="selisih-admin-notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="opsional" /></div>
      </div>
      <div className="flex gap-2 mt-4 justify-end">
        <Button variant="outline" onClick={onClose}>Batal</Button>
        <Button onClick={save} disabled={!status || saving} data-testid="selisih-vendor-status-save">{saving ? 'Menyimpan…' : 'Simpan'}</Button>
      </div>
    </Modal>
  );
}

/**
 * Laporan Selisih › Per baris PO — rantai satu baris PO dan selisihnya, dengan alasan yang sudah tercatat
 * (alasan lebih qty, tutup PO kurang, selisih kirim CMT / klien, laporan vendor). Kekurangan terhadap pesanan
 * baru dihitung setelah CMT selesai atau PO ditutup; selama berjalan, angka yang belum sampai bukan selisih.
 */
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Fragment, useMemo, useState } from 'react';
import { AlertCircle, Scale } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import { formatDateID } from '@/lib/format';
import { Badge, LoadingRows, RefreshButton, Section, Signed, n, useApi } from './pantauShared';
import { SelisihFilters, useSelisihFilter } from './selisihShared';

const KIND_META = {
  lebih: { label: 'Lebih', tone: 'warning' },
  kurang: { label: 'Kurang', tone: 'danger' },
  tertunda: { label: 'Menunggu tindakan', tone: 'info' },
};

export default function SelisihBarisTab() {
  const f = useSelisihFilter();
  const maklon = f.bt === 'maklon';
  const [view, setView] = useState('selisih');
  const [open, setOpen] = useState('');
  const { data, loading, error, reload } = useApi(`/pantau/selisih?${f.query}`);
  const all = useMemo(() => data?.rows || [], [data]);
  const counts = useMemo(() => ({
    selisih: all.filter((r) => r.has_diff).length,
    tanpa: all.filter((r) => r.has_diff && !r.has_reason).length,
    tertunda: all.filter((r) => r.differences.some((d) => d.kind === 'tertunda')).length,
  }), [all]);
  const rows = useMemo(() => all.filter((r) => {
    if (view === 'selisih') return r.has_diff;
    if (view === 'tanpa') return r.has_diff && !r.has_reason;
    if (view === 'tertunda') return r.differences.some((d) => d.kind === 'tertunda');
    return true;
  }), [all, view]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);
  const sm = data?.summary || {};
  const finalLabel = maklon ? 'Diterima klien' : 'Masuk stok';

  return (
    <PageLayout
      testId="selisih-baris"
      title="Per baris PO"
      filters={<>
        <SelisihFilters testId="selisih-baris-filter" />
        <FilterChips value={view} onChange={setView} testId="selisih-baris-view" ariaLabel="Tampilkan" hideWhenEmpty={false}
          options={[{ key: 'selisih', label: 'Ada selisih', count: counts.selisih },
            { key: 'tanpa', label: 'Tanpa alasan', count: counts.tanpa },
            { key: 'tertunda', label: 'Menunggu tindakan', count: counts.tertunda },
            { key: '', label: 'Semua baris', count: all.length }]} />
      </>}
      tools={<><TombolUnduh namaBerkas="selisih-per-baris-po" baris={rows} kolom={[
          { label: 'PO', nilai: (r) => r.po_number || '' }, { label: 'Vendor', nilai: (r) => r.vendor_name || '' },
          { label: 'SKU', nilai: (r) => r.sku || '' }, { label: 'Ukuran', nilai: (r) => r.size || '' }, { label: 'Warna', nilai: (r) => r.color || '' },
          { label: 'No. seri', nilai: (r) => r.serial_number || '' }, { label: 'Dipesan', nilai: (r) => Number(r.ordered) || 0 },
          { label: 'Bahan diterima CMT', nilai: (r) => Number(r.material_received) || 0 }, { label: 'Diproduksi', nilai: (r) => Number(r.produced) || 0 },
          { label: 'Lolos QC', nilai: (r) => Number(r.accepted) || 0 }, { label: 'Hasil akhir', nilai: (r) => Number(r.final) || 0 },
          { label: 'Selisih akhir', nilai: (r) => Number(r.final_gap) || 0 },
        ]} />
        <RefreshButton onClick={reload} loading={loading} testId="selisih-baris-refresh" /></>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
        {data && all.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="selisih-baris-kpi">
            <StatTile label="Baris ada selisih" value={n(sm.lines_diff)} sub={`dari ${n(sm.lines)} baris PO`} accent={sm.lines_diff ? 'warning' : 'muted'} testId="kpi-selisih-baris" />
            <StatTile label="Lebih dari pesanan" value={n(sm.lebih)} sub={`pcs ${finalLabel.toLowerCase()}`} accent={sm.lebih ? 'warning' : 'muted'} testId="kpi-selisih-lebih" />
            <StatTile label="Kurang dari pesanan" value={n(sm.kurang)} sub="pcs, setelah CMT selesai / PO ditutup" accent={sm.kurang ? 'danger' : 'muted'} testId="kpi-selisih-kurang" />
            {maklon
              ? <StatTile label="Belum dikonfirmasi klien" value={n(sm.belum_konfirmasi)} sub="pcs dikirim, belum dihitung diterima" accent={sm.belum_konfirmasi ? 'warning' : 'muted'} testId="kpi-selisih-konfirmasi" />
              : <StatTile label="Selisih tanpa alasan" value={n(sm.tanpa_alasan)} sub="baris yang perlu dijelaskan" accent={sm.tanpa_alasan ? 'danger' : 'muted'} testId="kpi-selisih-tanpa" />}
          </div>
        )}
      </>}
      footer={rows.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}
    >
      <Section>
        {loading && !data ? <LoadingRows /> : rows.length === 0 ? (
          <EmptyState icon={Scale} title={all.length ? 'Tidak ada baris pada pilihan ini' : 'Belum ada PO pada periode ini'}
            description={all.length ? 'Pilih “Semua baris” untuk melihat seluruh rantai.' : 'Ubah periode atau portal.'} />
        ) : (
          <Table data-testid="selisih-baris-table">
            <TableHeader><TableRow>
              <TableHead className="w-10" /><TableHead>PO</TableHead><TableHead>Barang</TableHead>
              <TableHead className="text-right">Dipesan</TableHead><TableHead className="text-right">Bahan diterima CMT</TableHead>
              <TableHead className="text-right">Diproduksi</TableHead><TableHead className="text-right">Lolos QC</TableHead>
              <TableHead className="text-right">{finalLabel}</TableHead><TableHead className="text-right">Selisih akhir</TableHead>
              <TableHead>Selisih</TableHead><TableHead>Alasan</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((r) => {
                const isOpen = open === r.po_item_id;
                const kinds = [...new Set(r.differences.map((d) => d.kind))];
                return (
                  <Fragment key={r.po_item_id}>
                    <TableRow data-testid={`selisih-row-${r.po_number}-${r.sku}-${r.size}`}>
                      <TableCell><RowToggle open={isOpen} onClick={() => setOpen(isOpen ? '' : r.po_item_id)} label="Lihat rantai dan alasan" testId={`selisih-toggle-${r.po_number}-${r.sku}-${r.size}`} /></TableCell>
                      <TableCell className="font-medium whitespace-nowrap">{r.po_number}<div className="text-xs text-muted-foreground">{r.vendor_name || '—'}</div></TableCell>
                      <TableCell className="whitespace-nowrap">{r.sku}<div className="text-xs text-muted-foreground">{[r.serial_number, r.size, r.color].filter(Boolean).join(' · ')}</div></TableCell>
                      <TableCell className="text-right tabular-nums">{n(r.ordered)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(r.material_received)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(r.produced)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(r.accepted)}</TableCell>
                      <TableCell className="text-right tabular-nums" data-testid="selisih-final">{n(r.final)}
                        {maklon && r.pending_confirm ? <div className="text-xs text-[hsl(var(--warning-text))]">+{n(r.pending_confirm)} belum dikonfirmasi</div> : null}</TableCell>
                      <TableCell className="text-right whitespace-nowrap" data-testid="selisih-gap">
                        {r.final_gap && !r.differences.some((d) => d.key === 'akhir_vs_pesan')
                          ? <span className="text-xs text-muted-foreground tabular-nums" title="Masih berjalan — belum dihitung selisih">{n(r.final_gap)} · berjalan</span>
                          : <Signed v={r.final_gap} />}</TableCell>
                      <TableCell className="space-x-1 whitespace-nowrap">{kinds.length ? kinds.map((k) => <Badge key={k} meta={KIND_META[k]} />) : <Badge meta={{ label: 'Sesuai', tone: 'success' }} />}</TableCell>
                      <TableCell>{r.has_diff ? (r.has_reason ? <Badge meta={{ label: 'Ada alasan', tone: 'success' }} /> : <Badge meta={{ label: 'Tanpa alasan', tone: 'danger' }} />) : (r.has_reason ? <Badge meta={{ label: 'Ada catatan', tone: 'default' }} /> : '—')}</TableCell>
                    </TableRow>
                    {isOpen && (
                      <RowDetail colSpan={11} testId={`selisih-detail-${r.po_number}-${r.sku}-${r.size}`}>
                        <LineDetail r={r} maklon={maklon} />
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

function LineDetail({ r, maklon }) {
  const chain = [
    ['Dipesan', r.ordered],
    ['Potongan dikirim ke CMT', r.sent_cmt, r.sent_extra ? `+${n(r.sent_extra)} pengganti/tambahan` : ''],
    ['Bahan diterima CMT', r.material_received, r.material_missing ? `kurang ${n(r.material_missing)}` : (r.material_uninspected ? `${n(r.material_uninspected)} belum diperiksa` : '')],
    ['Diproduksi CMT', r.produced],
    ['Sampai di DA', r.arrived, r.cmt_short_open ? `${n(r.cmt_short_open)} diklaim CMT belum sampai` : ''],
    ['Lolos QC (termasuk permak berhasil)', r.accepted, r.reject ? `ditolak ${n(r.reject)} · berhasil ${n(r.repaired)} · dibuang ${n(r.scrap)} · belum jelas ${n(r.reject_open)}` : ''],
    [maklon ? 'Dikirim ke klien' : 'Diserahkan ke gudang', r.dispatched],
    ...(maklon ? [['Diterima klien (dikonfirmasi)', r.received_confirmed, r.pending_confirm ? `${n(r.pending_confirm)} belum dikonfirmasi` : '']] : []),
  ];
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-1">
        <p className="text-xs font-semibold text-muted-foreground">Rantai barang</p>
        <Table data-testid="selisih-chain">
          <TableBody>
            {chain.map(([label, v, note]) => (
              <TableRow key={label}>
                <TableCell>{label}</TableCell>
                <TableCell className="text-right tabular-nums font-semibold">{n(v)}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{note || ''}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="space-y-3">
        <div className="space-y-1">
          <p className="text-xs font-semibold text-muted-foreground">Selisih</p>
          {r.differences.length === 0 ? <p className="text-sm text-muted-foreground">Tidak ada selisih pada baris ini.</p> : (
            <Table data-testid="selisih-diffs">
              <TableBody>
                {r.differences.map((d) => (
                  <TableRow key={d.key}>
                    <TableCell>{d.label}{d.note ? <div className="text-xs text-muted-foreground">{d.note}</div> : null}</TableCell>
                    <TableCell className="text-right"><Signed v={d.qty} /></TableCell>
                    <TableCell><Badge meta={KIND_META[d.kind]} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
        <div className="space-y-1">
          <p className="text-xs font-semibold text-muted-foreground">Alasan yang tercatat</p>
          {r.reasons.length === 0 ? (
            <p className="text-sm text-[hsl(var(--danger-text))]">{r.has_diff ? 'Belum ada alasan tercatat untuk selisih ini.' : 'Tidak ada catatan.'}</p>
          ) : (
            <Table data-testid="selisih-reasons">
              <TableBody>
                {r.reasons.map((x, i) => (
                  <TableRow key={`${x.kind}-${i}`}>
                    <TableCell className="whitespace-nowrap">{x.label}{x.open ? <div><Badge meta={{ label: 'Belum diputuskan', tone: 'warning' }} /></div> : null}</TableCell>
                    <TableCell className="text-right tabular-nums">{x.qty == null ? '—' : n(x.qty)}</TableCell>
                    <TableCell className="text-xs">{x.reason || '—'}<div className="text-xs text-muted-foreground">{[x.by, x.at ? formatDateID(x.at) : ''].filter(Boolean).join(' · ')}</div></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </div>
    </div>
  );
}

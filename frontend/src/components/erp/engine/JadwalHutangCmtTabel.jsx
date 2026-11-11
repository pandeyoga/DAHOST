/**
 * JadwalHutangCmtTabel — tabel "jadwal hutang CMT per PO" (qty × upah CMT per penjahit) di Portal Maklon › Tagihan CMT ›
 * "Jadwal hutang per PO": kolom dibayar / tertahan / bisa dibayar.
 *
 * 11 Nov 2026 (owner "tagihan tidak usah beda tab"): Keuangan tidak lagi memakai tabel ini sebagai tab tersendiri —
 * jadwal (CV Sukma) dan perkiraan PO DA tampil sebagai baris "Terjadwal" di SATU daftar Keuangan › Hutang
 * (`finance/HutangModule`), yang memakai rincian per barang `JadwalBarisBarang` dari sini.
 * Sumber: GET /api/production/cmt-billing/schedules (rumus server `maklon_ledger.ap_schedule_rows`).
 * PANDUAN_UI: rincian per barang di bawah barisnya (RowDetail); tabel kosong tetap tampil dengan EmptyState.
 */
import { Fragment, useState } from 'react';
import { Receipt } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';

export const fmtRp = (v) => `Rp ${Number(v || 0).toLocaleString('id-ID')}`;
export const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');
const STATUS = {
  draft: ['Draf', 'muted'], submitted: ['Diajukan', 'info'], approved: ['Disetujui', 'info'],
  posted: ['Terjurnal', 'info'], partial_paid: ['Dibayar sebagian', 'warning'], paid: ['Lunas', 'success'],
  cancelled: ['Dibatalkan', 'muted'], terjadwal: ['Terjadwal', 'info'], berjalan: ['Berjalan', 'warning'],
  lunas: ['Lunas', 'success'],
};
export const StatusPill = ({ status }) => {
  const [label, tone] = STATUS[(status || '').toLowerCase()] || [status || 'Draf', 'default'];
  return <StatusBadge status={label} tone={tone} />;
};
/** Belum jatuh tempo = jadwal − yang sudah lolos QC (server `remaining_amount`; data lama → dihitung). */
export const sisaJadwal = (s) => (s.remaining_amount ?? Math.max(0, Number(s.scheduled_amount || 0) - Number(s.matured_amount || 0)));

/** Rincian per barang satu jadwal (model/warna, ukuran, pcs × upah). */
export function JadwalBarisBarang({ lines, testId }) {
  if (!(lines || []).length) return <p className="text-sm text-muted-foreground" data-testid={testId}>Tidak ada rincian barang.</p>;
  return (
    <Table data-testid={testId}>
      <TableHeader><TableRow>
        <TableHead>Model / warna</TableHead><TableHead>Ukuran</TableHead>
        <TableHead className="text-right">Pcs</TableHead><TableHead className="text-right">Upah / pcs</TableHead>
        <TableHead className="text-right">Nilai</TableHead>
      </TableRow></TableHeader>
      <TableBody>{lines.map((ln) => (
        <TableRow key={ln.po_item_id}>
          <TableCell>
            {[ln.product_name, ln.color].filter(Boolean).join(' · ') || '—'}
            {ln.sku && <span className="block text-xs text-muted-foreground">{ln.sku}</span>}
          </TableCell>
          <TableCell>{ln.size || '—'}</TableCell>
          <TableCell className="text-right tabular-nums">{fmtNum(ln.qty)}</TableCell>
          <TableCell className="text-right tabular-nums">{fmtRp(ln.cmt_rate)}</TableCell>
          <TableCell className="text-right tabular-nums">{fmtRp(ln.amount)}</TableCell>
        </TableRow>
      ))}</TableBody>
    </Table>
  );
}

export default function JadwalHutangCmtTabel({ items, loading }) {
  const [open, setOpen] = useState(null);
  if (loading && !items.length) return <div className="p-4 text-sm text-muted-foreground">Memuat jadwal…</div>;
  const cols = 10;
  return (
    <Table data-testid="cmt-ap-schedules">
      <TableHeader><TableRow>
        <TableHead className="w-10" />
        <TableHead>PO</TableHead><TableHead>Vendor CMT</TableHead>
        <TableHead className="text-right">Jadwal (qty × upah)</TableHead>
        <TableHead className="text-right">Lolos QC</TableHead>
        <TableHead className="text-right">Belum jatuh tempo</TableHead>
        <TableHead className="text-right">Dibayar</TableHead><TableHead className="text-right">Tertahan</TableHead>
        <TableHead className="text-right">Bisa dibayar</TableHead>
        <TableHead>Status</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {items.length === 0 && (
          <TableRow className="hover:bg-transparent">
            <TableCell colSpan={cols} className="p-0 [&>div]:py-8">
              <EmptyState icon={Receipt} title="Belum ada jadwal hutang CMT"
                description="Jadwal lahir saat PO maklon dikonfirmasi: qty × upah CMT per vendor." />
            </TableCell>
          </TableRow>
        )}
        {items.map((s) => {
          const isOpen = open === s.id;
          return (
            <Fragment key={s.id}>
              <TableRow data-testid={`cmt-ap-row-${s.id}`}>
                <TableCell><RowToggle open={isOpen} onClick={() => setOpen(isOpen ? null : s.id)} label="Lihat per barang" /></TableCell>
                <TableCell className="font-medium whitespace-nowrap">{s.po_number}</TableCell>
                <TableCell>{s.vendor_name || 'Vendor belum ditentukan'}</TableCell>
                {/* angka kedua di baris bawah (bukan disambung) supaya tabel tidak melebar — Status tetap terlihat */}
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(s.scheduled_amount)}
                  <span className="block text-xs text-muted-foreground">{fmtNum(s.scheduled_qty)} pcs</span></TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(s.matured_amount)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap font-medium" data-testid={`cmt-ap-sisa-${s.po_number}`}>{fmtRp(sisaJadwal(s))}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(s.paid_amount)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">
                  {Number(s.blocked_amount || 0) > 0 ? <span className="text-[hsl(var(--danger-text))]">{fmtRp(s.blocked_amount)}</span> : fmtRp(0)}
                </TableCell>
                <TableCell className="text-right whitespace-nowrap" data-testid={`cmt-ap-payable-${s.po_number}`}>
                  <b className="tabular-nums">{fmtRp(s.payable_amount)}</b>
                  <span className="block text-xs text-muted-foreground tabular-nums">dari {fmtRp(Math.max(Number(s.scheduled_amount || 0), Number(s.matured_amount || 0)))}</span>
                </TableCell>
                <TableCell><StatusPill status={s.status} /></TableCell>
              </TableRow>
              {isOpen && (
                <RowDetail colSpan={cols} testId={`cmt-ap-lines-${s.id}`}>
                  <JadwalBarisBarang lines={s.lines} />
                </RowDetail>
              )}
            </Fragment>
          );
        })}
      </TableBody>
    </Table>
  );
}

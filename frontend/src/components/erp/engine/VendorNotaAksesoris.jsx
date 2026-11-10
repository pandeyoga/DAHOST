/**
 * Portal Vendor CMT › Nota Aksesoris — nota aksesoris yang dibeli CMT ini (permintaan owner 10–11 Nov 2026).
 * Hanya nota milik vendor yang masuk (server menyaring per vendor). Dibaca saja: nomor, kiriman/PO, total,
 * yang sudah dipotong dari tagihan jahit / dibayar langsung, sisa, dan PDF. Server: core/nota_aksesoris_cmt.py.
 */
import { useCallback, useEffect, useState } from 'react';
import { Download, Receipt, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { apiGet } from '../../../lib/api';
import { fmtRp } from './kirim/kirimShared';
import { ringkasBayar, unduhNotaPdf } from './kirim/NotaAksesorisKiriman';

const NADA = { issued: 'warning', overdue: 'warning', partial_paid: 'warning', paid: 'success', cancelled: 'muted' };
const TERBUKA = ['issued', 'overdue', 'partial_paid'];

export default function VendorNotaAksesoris() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const load = useCallback(async () => {
    setError('');
    try { const d = await apiGet('/kirim-cmt/nota-aksesoris'); setRows(Array.isArray(d) ? d : []); }
    catch (e) { setError(e.message || 'Nota gagal dimuat'); setRows([]); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const all = (rows || []).filter((r) => r.status !== 'cancelled');
  const shown = all.filter((r) => (status === 'terbuka' ? TERBUKA.includes(r.status)
    : status === 'lunas' ? r.status === 'paid' : true));
  const sisa = all.reduce((t, r) => t + (TERBUKA.includes(r.status) ? Number(r.balance) || 0 : 0), 0);

  return (
    <PageLayout testId="vendor-nota-aksesoris" title="Nota aksesoris"
      subtitle="Aksesoris yang Anda beli saat menerima kiriman — dipotong dari tagihan jahit atau dibayar langsung."
      filters={<FilterChips value={status} onChange={setStatus} ariaLabel="Status nota" testId="vendor-nota-status"
        options={[{ key: '', label: 'Semua', count: all.length },
          { key: 'terbuka', label: 'Belum lunas', count: all.filter((r) => TERBUKA.includes(r.status)).length },
          { key: 'lunas', label: 'Lunas', count: all.filter((r) => r.status === 'paid').length }]} hideWhenEmpty={false} />}
      tools={<Button type="button" variant="outline" size="icon" title="Muat ulang" aria-label="Muat ulang" onClick={load}>
        <RefreshCw className="w-4 h-4" /></Button>}
      summary={rows && <p className="text-sm" data-testid="vendor-nota-sisa">Sisa yang belum dibayar/dipotong: <b className="tabular-nums">{fmtRp(sisa)}</b></p>}>
      {error && <Notice tone="danger" icon={Receipt}>{error}</Notice>}
      <div className="overflow-x-auto">
        <Table data-testid="vendor-nota-tabel">
          <TableHeader><TableRow>
            <TableHead>No. nota</TableHead><TableHead>Tanggal</TableHead><TableHead>Kiriman / PO</TableHead>
            <TableHead className="text-right">Total</TableHead><TableHead>Pembayaran</TableHead><TableHead>Status</TableHead>
            <TableHead className="text-right">Cetak</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {rows === null && (
              <TableRow><TableCell colSpan={7} className="text-sm text-muted-foreground">Memuat…</TableCell></TableRow>
            )}
            {rows !== null && !shown.length && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={7} className="p-0 [&>div]:py-6">
                  <EmptyState icon={Receipt} title="Belum ada nota aksesoris"
                    description="Nota terbit saat aksesoris diserahkan bersama kiriman potongan." />
                </TableCell>
              </TableRow>
            )}
            {shown.map((r) => (
              <TableRow key={r.id} data-testid={`vendor-nota-row-${r.invoice_number}`}>
                <TableCell className="font-medium whitespace-nowrap">{r.invoice_number}</TableCell>
                <TableCell className="text-sm whitespace-nowrap">{formatDateID(r.issue_date)}</TableCell>
                <TableCell className="text-sm">{r.shipment_number || '—'}
                  <span className="block text-xs text-muted-foreground">{r.po_number ? `PO ${r.po_number}` : ''}</span></TableCell>
                <TableCell className="text-right tabular-nums">{fmtRp(r.total)}</TableCell>
                <TableCell className="text-sm">{r.cara_bayar_label}
                  <span className="block text-xs text-muted-foreground">{ringkasBayar(r)}</span></TableCell>
                <TableCell><StatusBadge status={r.status} label={r.status_label} tone={NADA[r.status] || 'default'} /></TableCell>
                <TableCell className="text-right">
                  <Button type="button" variant="outline" size="icon" title="Cetak nota" aria-label={`Cetak nota ${r.invoice_number}`}
                    onClick={() => unduhNotaPdf(r)} data-testid={`vendor-nota-pdf-${r.invoice_number}`}><Download className="w-4 h-4" /></Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </PageLayout>
  );
}

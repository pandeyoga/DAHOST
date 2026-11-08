/**
 * Dashboard Maklon › Ringkasan klien — jumlah klien & order maklon + order terbaru.
 * Sumber: /api/dewi/maklon/summary + /api/dewi/maklon/pos + /api/dewi/maklon/clients.
 *
 * Standar UI/UX v2 (8 Nov 2026): tabel order bisa diunduh, ukuran huruf standar.
 * Perbaikan angka (keputusan 9): "Klien aktif" kini dihitung dengan aturan yang SAMA dengan menu Klien
 * (aktif = status bukan "nonaktif", dari daftar klien). Dulu memakai hitungan server `status == 'active'` sehingga
 * klien hasil impor tanpa kolom status (mis. SnBM) tidak terhitung: kartu "1 dari 2" sementara menu Klien "Aktif (2)".
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Package } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { posToLegacyOrders } from '@/lib/maklonOrderAdapter';
import { formatDateID, formatRupiah } from '@/lib/format';
import { LoadingRows, RefreshButton, Section, n } from './pantauShared';

const ORDER_STATUS = {
  draft: { label: 'Draf', tone: 'muted' }, confirmed: { label: 'Dikonfirmasi', tone: 'info' },
  material_ready: { label: 'Bahan siap', tone: 'info' }, cutting: { label: 'Dipotong', tone: 'info' },
  sewing: { label: 'Dijahit', tone: 'info' }, qc: { label: 'QC', tone: 'warning' }, packing: { label: 'Dikemas', tone: 'warning' },
  completed: { label: 'Selesai', tone: 'success' }, invoiced: { label: 'Ditagih', tone: 'success' },
  cancelled: { label: 'Dibatalkan', tone: 'danger' },
};
const labelStatus = (s) => (ORDER_STATUS[s] || {}).label || s || '—';

export default function MaklonRingkasanKlienTab({ token, onNavigate }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [summary, setSummary] = useState({});
  const [orders, setOrders] = useState([]);
  const [clients, setClients] = useState(null);   // null = daftar klien gagal/ belum dimuat
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [s, o, c] = await Promise.all([
        fetch('/api/dewi/maklon/summary', { headers }), fetch('/api/dewi/maklon/pos', { headers }),
        fetch('/api/dewi/maklon/clients', { headers }).catch(() => null),
      ]);
      if (s.ok) setSummary(await s.json());
      if (o.ok) setOrders(posToLegacyOrders(await o.json()).slice(0, 50));
      if (c && c.ok) { const d = await c.json(); setClients(Array.isArray(d) ? d : null); } else setClients(null);
      if (!s.ok && !o.ok) setError('Ringkasan maklon gagal dimuat');
    } catch (e) { setError(e.message || 'Ringkasan maklon gagal dimuat'); }
    finally { setLoading(false); }
  }, [headers]);
  useEffect(() => { load(); }, [load]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(orders, 10);
  // Aturan sama dengan menu Klien (MaklonClientManagement.isActive)
  const klienAktif = clients ? clients.filter((c) => c?.status !== 'inactive').length : summary.active_clients;
  const klienTotal = clients ? clients.length : summary.total_clients;

  return (
    <PageLayout
      testId="maklon-ringkasan-klien"
      title="Ringkasan klien"
      actions={<>
        <Button variant="outline" onClick={() => onNavigate && onNavigate('maklon-clients')} data-testid="btn-kelola-klien">Kelola klien</Button>
        <Button variant="outline" onClick={() => onNavigate && onNavigate('maklon-pos-engine')} data-testid="btn-kelola-order">Kelola order</Button>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="order-maklon-terbaru" namaLembar="Order terbaru" baris={orders} testId="maklon-recent-unduh"
          kolom={[
            { label: 'Order', nilai: (o) => o.order_code }, { label: 'Klien', nilai: (o) => o.client_name || '' },
            { label: 'Produk', nilai: (o) => o.product_name || '' }, { label: 'Kategori', nilai: (o) => o.product_category || '' },
            { label: 'Qty', nilai: (o) => Number(o.qty_ordered || 0) }, { label: 'Nilai order', nilai: (o) => Number(o.total_value || 0) },
            { label: 'Batas kirim', nilai: (o) => (o.deadline_date ? formatDateID(o.deadline_date) : '') },
            { label: 'Progres %', nilai: (o) => Number(o.progress_percentage || 0) }, { label: 'Status', nilai: (o) => labelStatus(o.status) },
          ]} />
        <RefreshButton onClick={load} loading={loading} testId="refresh-dashboard" />
      </>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="maklon-klien-kpi">
          <StatTile label="Klien aktif" value={n(klienAktif)} sub={`Dari ${n(klienTotal)} klien terdaftar`} />
          <StatTile label="Order aktif" value={n(summary.active_orders)}
            sub={`${n(summary.draft_orders)} draf · ${n(summary.confirmed_orders)} dikonfirmasi · ${n(summary.in_production)} produksi`} />
          <StatTile label="Order selesai" value={n(summary.completed_orders)} sub={`Dari ${n(summary.total_orders)} order maklon`} />
          <StatTile label="Nilai order" value={formatRupiah(summary.total_revenue)} sub="Total nilai PO maklon" />
        </div>
      </>}
      footer={orders.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}
    >
      <Section title="Order terbaru">
        {loading && !orders.length ? <LoadingRows /> : (
          <Table data-testid="maklon-recent-orders">
            <TableHeader><TableRow>
              <TableHead>Order</TableHead><TableHead>Klien</TableHead><TableHead>Produk</TableHead>
              <TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Nilai order</TableHead>
              <TableHead>Batas kirim</TableHead><TableHead className="text-right">Progres</TableHead><TableHead>Status</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {orders.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={8} className="p-0 [&>div]:py-8"><EmptyState icon={Package} title="Belum ada order maklon" description="Buat PO maklon pertama di menu PO Maklon; order terbaru akan tampil di sini." /></TableCell>
                </TableRow>
              )}
              {paged.map((o) => (
                <TableRow key={o.id}>
                  <TableCell className="font-medium whitespace-nowrap">{o.order_code}</TableCell>
                  <TableCell>{o.client_name}</TableCell>
                  <TableCell>{o.product_name}{o.product_category ? <div className="text-xs text-muted-foreground">{o.product_category}</div> : null}</TableCell>
                  <TableCell className="text-right tabular-nums">{n(o.qty_ordered)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{formatRupiah(o.total_value)}</TableCell>
                  <TableCell className="whitespace-nowrap">{o.deadline_date ? formatDateID(o.deadline_date) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{n(o.progress_percentage)}%</TableCell>
                  <TableCell><StatusBadge label={labelStatus(o.status)} tone={(ORDER_STATUS[o.status] || {}).tone || 'default'} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
    </PageLayout>
  );
}

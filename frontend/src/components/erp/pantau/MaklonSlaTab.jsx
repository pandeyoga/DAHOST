/**
 * Dashboard Maklon › SLA per klien — ketepatan waktu order per klien. Buka baris (RowDetail) untuk order klien
 * itu (dulu tampilan diganti seluruhnya + tombol "Kembali"). Sumber: /api/maklon/sla/*.
 */
import { Fragment, useCallback, useEffect, useState } from 'react';
import { AlertCircle, Users } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import { Skeleton } from '@/components/ui/skeleton';
import apiFetch from '@/lib/apiFetch';
import { formatDateID } from '@/lib/format';
import { Badge, LoadingRows, RefreshButton, Section, n, pct } from './pantauShared';

const PERIODS = [{ value: '30', label: '30 hari' }, { value: '60', label: '60 hari' }, { value: '90', label: '90 hari' }, { value: '180', label: '6 bulan' }];
const SLA_META = { good: { label: 'Baik', tone: 'success' }, warning: { label: 'Perlu perhatian', tone: 'warning' }, poor: { label: 'Buruk', tone: 'danger' } };
// Klien tanpa order selesai tidak bisa dinilai — dulu server menilainya "Buruk" (rate kosong dianggap 0%).
const slaMeta = (c) => (c.on_time_rate == null ? { label: 'Belum bisa dinilai', tone: 'muted' } : SLA_META[c.sla_status]);
const ORDER_META = { on_time: { label: 'Tepat waktu', tone: 'success' }, late: { label: 'Terlambat', tone: 'danger' } };

export default function MaklonSlaTab() {
  const [days, setDays] = useState('90');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [open, setOpen] = useState('');
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { setData(await apiFetch(`/maklon/sla/dashboard?days=${days}`)); }
    catch (e) { setError(e.message || 'SLA gagal dimuat'); }
    finally { setLoading(false); }
  }, [days]);
  useEffect(() => { load(); }, [load]);
  const items = data?.data || [];
  const meta = data?.metadata || {};

  return (
    <PageLayout
      testId="maklon-sla"
      title="SLA per klien"
      filters={<SmartNativeSelect value={days} onChange={(e) => setDays(e.target.value)} searchable={false} className="h-9 w-36" aria-label="Periode" data-testid="sla-period">
        {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
      </SmartNativeSelect>}
      tools={<>
        <TombolUnduh namaBerkas={`sla-klien-maklon-${days}-hari`} namaLembar="SLA per klien" baris={items} testId="sla-unduh"
          kolom={[
            { label: 'Klien', nilai: (c) => c.client_name || '' }, { label: 'Order', nilai: (c) => Number(c.total_orders || 0) },
            { label: 'Selesai', nilai: (c) => Number(c.completed_orders || 0) }, { label: 'Tepat waktu', nilai: (c) => Number(c.on_time || 0) },
            { label: 'Terlambat', nilai: (c) => Number(c.late || 0) },
            { label: 'Ketepatan %', nilai: (c) => (c.on_time_rate == null ? '' : Number(c.on_time_rate)) },
            { label: 'Rata-rata hari', nilai: (c) => (c.avg_lead_days ? Number(c.avg_lead_days) : '') },
            { label: 'Status', nilai: (c) => (slaMeta(c) || {}).label || '' },
          ]} />
        <RefreshButton onClick={load} loading={loading} testId="btn-refresh-sla" />
      </>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
        {items.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatTile label="Klien" value={n(meta.total_clients)} sub="Punya order dalam periode ini" />
            <StatTile label="Order" value={n(meta.total_orders)} sub={`${n(meta.total_completed)} sudah selesai`} />
            <StatTile label="Tepat waktu" value={meta.overall_on_time_rate == null ? '—' : pct(meta.overall_on_time_rate)}
              sub={meta.overall_on_time_rate == null ? 'Belum ada order selesai' : 'Dari order yang sudah selesai'} />
            <StatTile label="Rata-rata lama kerja" value={meta.overall_avg_lead_days ? `${n(meta.overall_avg_lead_days)} hari` : '—'}
              sub={meta.overall_avg_lead_days ? 'Rata-rata dari rata-rata tiap klien' : 'Belum ada order selesai'} />
          </div>
        )}
      </>}
    >
      <Section>
        {loading && !data ? <LoadingRows /> : items.length === 0 ? (
          <EmptyState icon={Users} title="Belum ada order dalam periode ini" description="Pilih periode yang lebih panjang untuk melihat SLA per klien." />
        ) : (
          <Table data-testid="sla-table">
            <TableHeader><TableRow>
              <TableHead className="w-10" /><TableHead>Klien</TableHead><TableHead className="text-right">Order</TableHead>
              <TableHead className="text-right">Selesai</TableHead><TableHead className="text-right">Tepat waktu</TableHead>
              <TableHead className="text-right">Terlambat</TableHead><TableHead className="text-right">Ketepatan</TableHead>
              <TableHead className="text-right">Rata-rata hari</TableHead><TableHead>Status</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {items.map((c, i) => {
                const key = c.client_id || String(i);
                const isOpen = open === key;
                return (
                  <Fragment key={key}>
                    <TableRow data-testid={`sla-client-${i}`}>
                      <TableCell><RowToggle open={isOpen} onClick={() => setOpen(isOpen ? '' : key)} label="Lihat order klien" /></TableCell>
                      <TableCell className="font-medium">{c.client_name}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(c.total_orders)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(c.completed_orders)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(c.on_time)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(c.late)}</TableCell>
                      <TableCell className="text-right tabular-nums">{c.on_time_rate == null ? '—' : pct(c.on_time_rate)}</TableCell>
                      <TableCell className="text-right tabular-nums">{c.avg_lead_days ? n(c.avg_lead_days) : '—'}</TableCell>
                      <TableCell><Badge meta={slaMeta(c)} /></TableCell>
                    </TableRow>
                    {isOpen && <RowDetail colSpan={9}><ClientOrders clientId={c.client_id} days={days} /></RowDetail>}
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

function ClientOrders({ clientId, days }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let alive = true;
    apiFetch(`/maklon/sla/client/${clientId}?days=${days}`)
      .then((r) => { if (alive) setRows(r?.data?.orders || []); })
      .catch(() => { if (alive) setRows([]); });
    return () => { alive = false; };
  }, [clientId, days]);
  if (rows === null) return <Skeleton className="h-16 rounded-lg" />;
  if (!rows.length) return <p className="text-sm text-muted-foreground">Klien ini tidak punya order dalam periode ini.</p>;
  return (
    <Table>
      <TableHeader><TableRow>
        <TableHead>Order</TableHead><TableHead>Jenis</TableHead><TableHead>Batas kirim</TableHead>
        <TableHead>Tahap</TableHead><TableHead className="text-right">Lama (hari)</TableHead><TableHead>Status</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {rows.map((o, i) => (
          <TableRow key={o.order_code || i}>
            <TableCell className="font-medium">{o.order_code}</TableCell>
            <TableCell>{o.garment_type || '—'}</TableCell>
            <TableCell>{o.deadline_date ? formatDateID(o.deadline_date) : '—'}</TableCell>
            <TableCell>{o.stage || '—'}</TableCell>
            <TableCell className="text-right tabular-nums">{o.lead_days ? n(o.lead_days) : '—'}</TableCell>
            <TableCell><Badge meta={ORDER_META[o.status] || { label: 'Berjalan', tone: 'warning' }} /></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

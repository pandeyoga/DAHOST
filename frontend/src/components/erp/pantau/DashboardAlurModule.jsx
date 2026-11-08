/**
 * Dashboard Produksi / Dashboard Maklon — bagian alur (Tahap 9, keputusan owner no. 2 & 7: tampilan identik).
 *
 * Sama persis di dua portal; hanya saringan PO yang beda (Produksi = PO internal, Maklon = PO maklon).
 * Angka dari /api/pantau/ringkasan (sumber yang sama dengan Pantau Produksi), sehingga "Di vendor CMT" =
 * potongan yang belum disetor (bukan dikurangi kiriman berstatus "Received" yang berarti CMT menerima bahan),
 * dan serah terima / kirim ke klien tidak ikut menghitung surat jalan CMT → DA.
 */
import { AlertTriangle, CheckCircle2, ListChecks } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import {
  Badge, LoadingRows, RefreshButton, Section, n, pct, poStatusLabel, portalBusinessType, useApi,
} from './pantauShared';

const SEVERITY = { error: { label: 'Penting', tone: 'danger' }, warning: { label: 'Perhatian', tone: 'warning' }, info: { label: 'Catatan', tone: 'info' } };

/** Isi Dashboard sebagai props cetakan PageLayout — dipakai Dashboard Produksi dan tab alur Dashboard Maklon
 *  supaya keduanya identik (satu definisi). */
export function useDashboardAlur(props) {
  const bt = portalBusinessType(props);
  const { onNavigate } = props;
  const { data, loading, error, reload } = useApi(`/pantau/ringkasan?business_type=${bt}&days=7`, { auto: 60000 });
  const next = useApi(`/rahaza/next-actions?portal=${bt === 'maklon' ? 'maklon' : 'production'}&limit=12`);
  const actions = (next.data?.actions || []).filter((a) => a.cta_module && a.cta_module !== '__setup_wizard__').slice(0, 6);
  const k = data?.kpi || {};
  const done = data?.done || {};
  const go = (m, params) => onNavigate && m && onNavigate(m, params);

  return {
    testId: bt === 'maklon' ? 'maklon-dashboard-alur' : 'production-dashboard',
    title: bt === 'maklon' ? 'Dashboard Maklon' : 'Dashboard Produksi',
    subtitle: 'Perjalanan barang: bahan ke CMT, jahit, QC, sampai hasil akhirnya.',
    actions: <Button type="button" variant="outline" onClick={() => go('pantau-produksi')} data-testid="dash-open-pantau">Buka Pantau Produksi</Button>,
    tools: <RefreshButton onClick={() => { reload(); next.reload(); }} loading={loading} testId="dash-refresh" />,
    summary: <>
        {error && <Notice tone="danger" icon={AlertTriangle}>{error}</Notice>}
        {data && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="dash-kpi">
            <StatTile label="PO berjalan" value={n(k.po_berjalan)} sub={`${n(k.qty_berjalan)} pcs dipesan`} testId="dash-kpi-po" />
            <StatTile label="Di vendor CMT" value={n(k.di_cmt)} sub="pcs potongan belum disetor" accent={k.di_cmt ? 'warning' : 'muted'} testId="dash-kpi-dicmt" />
            <StatTile label="Lolos QC 7 hari" value={n(done.qc_window)} sub={`hari ini ${n(done.qc_today)} pcs`} testId="dash-kpi-qc" />
            <StatTile label="Tingkat ditolak QC" value={pct(k.reject_rate)} sub={`${n(k.telat)} PO lewat batas kirim`} accent={k.reject_rate > 5 ? 'warning' : 'default'} testId="dash-kpi-reject" />
          </div>
        )}
      </>,
    children: loading && !data ? <Section><LoadingRows /></Section> : data && <>
        <Section title="Alur barang" hint="Jumlah barang yang sedang berada di tiap tahap (PO berjalan)." testId="dash-alur"
          unduh={{ namaBerkas: 'alur-barang', baris: data.alur || [], kolom: [
            { label: 'Tahap', nilai: (s) => s.label }, { label: 'Pcs', nilai: (s) => Number(s.qty) || 0 },
            { label: 'Dokumen', nilai: (s) => Number(s.docs) || 0 }, { label: 'Jenis dokumen', nilai: (s) => s.doc_label || '' },
            { label: 'Catatan', nilai: (s) => s.note || '' },
          ] }}>
          <Table data-testid="dash-alur-table">
            <TableHeader><TableRow>
              <TableHead>Tahap</TableHead><TableHead className="text-right">Pcs</TableHead>
              <TableHead className="text-right">Dokumen</TableHead><TableHead className="text-right">Buka</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {data.alur.map((s) => (
                <TableRow key={s.key} data-testid={`dash-alur-${s.key}`}>
                  <TableCell className="font-medium">{s.label}{s.note ? <div className="text-xs text-muted-foreground">{s.note}</div> : null}</TableCell>
                  <TableCell className="text-right tabular-nums font-semibold" data-testid={`dash-alur-${s.key}-qty`}>{n(s.qty)}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{n(s.docs)} {s.doc_label}</TableCell>
                  <TableCell className="text-right"><Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => go(s.module)}>Buka</Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Section>

        {!data.balance?.all_ok && (
          <Notice tone="warning" icon={AlertTriangle} testId="dash-balance-warning"
            action={<Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => go('pantau-produksi')}>Lihat PO penyebab</Button>}>
            {(data.balance?.checks || []).filter((c) => !c.ok).map((c) => `${c.label}: ${n(c.offender_count)} PO tidak cocok`).join(' · ')}
          </Notice>
        )}

        {actions.length > 0 && (
          <Section title="Perlu ditindaklanjuti" testId="dash-next-actions" unduh={{ namaBerkas: 'perlu-ditindaklanjuti', baris: actions, kolom: [
            { label: 'Hal', nilai: (a) => a.title || '' }, { label: 'Keterangan', nilai: (a) => a.description || '' },
            { label: 'Tingkat', nilai: (a) => (SEVERITY[a.severity] || SEVERITY.info).label },
          ] }}>
            <Table>
              <TableHeader><TableRow>
                <TableHead>Hal</TableHead><TableHead>Tingkat</TableHead><TableHead className="text-right">Buka</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {actions.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>{a.title}{a.description ? <div className="text-xs text-muted-foreground">{a.description}</div> : null}</TableCell>
                    <TableCell><Badge meta={SEVERITY[a.severity] || SEVERITY.info} /></TableCell>
                    <TableCell className="text-right"><Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => go(a.cta_module, a.cta_params)}>{a.cta_label || 'Buka'}</Button></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>
        )}

        <Section title="PO paling lama tidak bergerak" hint="PO yang diam ≥ 7 hari biasanya menunggu kiriman bahan, setoran CMT, atau QC." testId="dash-aging"
          unduh={{ namaBerkas: 'po-tidak-bergerak', baris: data.aging || [], kolom: [
            { label: 'PO', nilai: (a) => a.po_number }, { label: 'Pemesan', nilai: (a) => a.customer_name || '' },
            { label: 'Vendor CMT', nilai: (a) => a.vendor_name || '' }, { label: 'Status', nilai: (a) => poStatusLabel(a.status) },
            { label: 'Diam (hari)', nilai: (a) => Number(a.idle_days) || 0 },
          ] }}>
          {data.aging.length === 0 ? (
            <EmptyState icon={CheckCircle2} title="Tidak ada PO berjalan" description="PO baru dibuat di menu PO." />
          ) : (
            <Table data-testid="dash-aging-table">
              <TableHeader><TableRow>
                <TableHead>PO</TableHead><TableHead>Pemesan</TableHead><TableHead>Vendor CMT</TableHead><TableHead>Status</TableHead>
                <TableHead className="text-right">Diam</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {data.aging.map((a) => (
                  <TableRow key={a.po_id}>
                    <TableCell className="font-medium whitespace-nowrap">{a.po_number}</TableCell>
                    <TableCell>{a.customer_name || '—'}</TableCell>
                    <TableCell>{a.vendor_name || '—'}</TableCell>
                    <TableCell>{poStatusLabel(a.status)}</TableCell>
                    <TableCell className={`text-right tabular-nums ${a.idle_days >= 7 ? 'text-[hsl(var(--warning-text))] font-semibold' : ''}`}>{n(a.idle_days)} hari</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Section>
        {data.overdue.length > 0 && (
          <Notice tone="danger" icon={ListChecks} testId="dash-overdue"
            action={<Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => go('pantau-produksi')}>Buka</Button>}>
            {n(data.overdue.filter((r) => r.risk === 'telat').length)} PO lewat batas kirim dan {n(data.overdue.filter((r) => r.risk === 'berisiko').length)} PO berisiko telat.
          </Notice>
        )}
      </>,
  };
}

export default function DashboardAlurModule(props) {
  const page = useDashboardAlur(props);
  return <PageLayout {...page} />;
}

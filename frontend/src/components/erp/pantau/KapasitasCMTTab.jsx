/**
 * Pantau Produksi › Kapasitas CMT — beban di CMT vs kapasitas per vendor. Beban = potongan yang masih di CMT
 * dari SEMUA PO berjalan (internal + maklon — satu CMT mengerjakan keduanya; dulu hanya maklon). Ditambah laju
 * setor nyata (pcs lolos QC per hari) dan cek order baru: pengganti Kapasitas di Analitik Produksi yang
 * memakai data lini/mesin yang sudah tidak dipakai (keputusan owner no. 11).
 */
import TombolUnduh from '@/components/ui/tombol-unduh';
import { useState } from 'react';
import { AlertCircle, CheckCircle2, Gauge, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { GlassInput } from '@/components/ui/glass';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import { apiGet } from '../../../lib/api';
import { Badge, LoadingRows, RefreshButton, Section, n, pct, portalBusinessType, useApi } from './pantauShared';

const CAP_META = {
  over: { label: 'Kelebihan beban', tone: 'danger' },
  near: { label: 'Hampir penuh', tone: 'warning' },
  ok: { label: 'Aman', tone: 'success' },
  no_capacity: { label: 'Kapasitas belum diisi', tone: 'muted' },
};

export default function KapasitasCMTTab(props) {
  const bt = portalBusinessType(props);
  const { data, loading, error, reload } = useApi(`/pantau/kapasitas?business_type=${bt}&window_days=30`);
  const t = data?.totals || {};
  const vendors = data?.vendors || [];
  const [qty, setQty] = useState('');
  const [days, setDays] = useState('14');
  const [vendor, setVendor] = useState('');
  const [check, setCheck] = useState(null);
  const [checking, setChecking] = useState(false);
  const [checkErr, setCheckErr] = useState('');
  const runCheck = async () => {
    setChecking(true); setCheckErr('');
    try {
      setCheck(await apiGet(`/pantau/kapasitas/cek?business_type=${bt}&qty=${Number(qty)}&target_days=${Number(days) || 14}${vendor ? `&vendor_id=${encodeURIComponent(vendor)}` : ''}`));
    } catch (e) { setCheckErr(e.message); setCheck(null); }
    finally { setChecking(false); }
  };

  return (
    <PageLayout
      testId="pantau-kapasitas"
      title="Kapasitas CMT"
      tools={<><TombolUnduh namaBerkas="kapasitas-cmt" baris={vendors} kolom={[
          { label: 'Vendor', nilai: (v) => v.name || '' }, { label: 'Kode', nilai: (v) => v.code || '' },
          { label: 'Beban internal (pcs)', nilai: (v) => Number(v.load_internal_pcs) || 0 }, { label: 'Beban maklon (pcs)', nilai: (v) => Number(v.load_maklon_pcs) || 0 },
          { label: 'Total beban (pcs)', nilai: (v) => Number(v.current_load_pcs) || 0 }, { label: 'Kapasitas (pcs)', nilai: (v) => (v.capacity_pcs == null ? '' : Number(v.capacity_pcs)) },
          { label: 'Sisa (pcs)', nilai: (v) => (v.available_pcs == null ? '' : Number(v.available_pcs)) },
          { label: 'Terpakai (%)', nilai: (v) => (v.utilization_pct == null ? '' : Number(v.utilization_pct)) },
          { label: 'Laju per hari', nilai: (v) => Number(v.daily_rate) || 0 }, { label: 'Perkiraan habis (hari)', nilai: (v) => (v.days_to_clear == null ? '' : Number(v.days_to_clear)) },
          { label: 'PO telat', nilai: (v) => Number(v.telat_po_count) || 0 }, { label: 'Keadaan', nilai: (v) => v.status || '' },
        ]} />
        <RefreshButton onClick={reload} loading={loading} testId="pantau-kapasitas-refresh" /></>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
        {data && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="pantau-kapasitas-kpi">
            <StatTile label="Kapasitas semua CMT" value={n(t.capacity_pcs)} sub={`${n(t.no_capacity_count)} vendor belum diisi kapasitasnya`} />
            <StatTile label="Beban di CMT" value={n(t.load_pcs)} sub={`internal ${n(t.load_internal_pcs)} · maklon ${n(t.load_maklon_pcs)}`} testId="kpi-beban" />
            <StatTile label="Sisa kapasitas" value={n(t.available_pcs)} accent={t.available_pcs < 0 ? 'danger' : 'default'}
              sub={t.utilization_pct == null ? 'kapasitas belum diisi' : `terpakai ${pct(t.utilization_pct)}`} />
            <StatTile label="Laju setor" value={`${n(t.daily_rate)}/hari`} sub={`pcs lolos QC, rata-rata ${n(data.window_days)} hari terakhir`} />
          </div>
        )}
      </>}
    >
      <Section title="Cek order baru" hint="Muat atau tidak, dari sisa kapasitas dan laju setor nyata." testId="pantau-kapasitas-cek">
        <div className="p-4 space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <div><label className="text-xs text-muted-foreground" htmlFor="cek-qty">Jumlah (pcs)</label>
              <GlassInput id="cek-qty" type="number" min="1" className="h-9 w-32" value={qty} onChange={(e) => setQty(e.target.value)} data-testid="pantau-cek-qty" /></div>
            <div><label className="text-xs text-muted-foreground" htmlFor="cek-days">Target selesai (hari)</label>
              <GlassInput id="cek-days" type="number" min="1" className="h-9 w-32" value={days} onChange={(e) => setDays(e.target.value)} data-testid="pantau-cek-days" /></div>
            <div className="min-w-[220px]"><label className="text-xs text-muted-foreground">Vendor CMT</label>
              <SmartNativeSelect value={vendor} onChange={(e) => setVendor(e.target.value)} className="h-9 w-full" aria-label="Vendor CMT" data-testid="pantau-cek-vendor">
                <option value="">Semua vendor</option>
                {vendors.map((v) => <option key={v.vendor_id} value={v.vendor_id}>{v.name}</option>)}
              </SmartNativeSelect></div>
            <Button onClick={runCheck} disabled={!(Number(qty) > 0) || checking} data-testid="pantau-cek-run">{checking ? 'Menghitung…' : 'Cek order'}</Button>
          </div>
          {checkErr && <Notice tone="danger" icon={AlertCircle}>{checkErr}</Notice>}
          {check && (
            <Notice tone={check.feasible ? 'success' : 'warning'} icon={check.feasible ? CheckCircle2 : XCircle} testId="pantau-cek-result"
              title={check.feasible ? `Muat — perkiraan selesai ${n(check.days_needed)} hari` : 'Belum muat dengan kapasitas sekarang'}>
              Beban sekarang {n(check.current_load)} pcs · sisa kapasitas {n(check.room_pcs)} pcs · laju {n(check.daily_rate)} pcs/hari
              {check.days_needed != null ? ` · beban + order ini selesai ±${n(check.days_needed)} hari` : ''}.
              {(check.warnings || []).length > 0 && <span> {check.warnings.join(' ')}</span>}
            </Notice>
          )}
        </div>
      </Section>

      <Section title="Beban per vendor" testId="pantau-kapasitas-vendor">
        {loading && !data ? <LoadingRows /> : vendors.length === 0 ? (
          <EmptyState icon={Gauge} title="Belum ada vendor CMT" description="Tambah vendor dan kapasitasnya di menu Vendor CMT." />
        ) : (
          <Table data-testid="pantau-kapasitas-table">
            <TableHeader><TableRow>
              <TableHead>Vendor</TableHead><TableHead className="text-right">Kapasitas</TableHead>
              <TableHead className="text-right">Beban internal</TableHead><TableHead className="text-right">Beban maklon</TableHead>
              <TableHead className="text-right">Total beban</TableHead><TableHead className="text-right">Terpakai</TableHead>
              <TableHead className="text-right">Sisa</TableHead><TableHead className="text-right">Laju/hari</TableHead>
              <TableHead className="text-right">Perkiraan habis</TableHead><TableHead className="text-right">PO telat</TableHead><TableHead>Keadaan</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {vendors.map((v) => (
                <TableRow key={v.vendor_id} data-testid={`pantau-kapasitas-row-${v.code || v.name}`}>
                  <TableCell className="font-medium">{v.name}{v.code ? <span className="text-xs text-muted-foreground"> · {v.code}</span> : null}
                    {v.capacity_note ? <div className="text-xs text-muted-foreground">{v.capacity_note}</div> : null}</TableCell>
                  <TableCell className="text-right tabular-nums">{v.capacity_pcs ? n(v.capacity_pcs) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums" data-testid="pantau-kap-internal">{n(v.load_internal_pcs)}</TableCell>
                  <TableCell className="text-right tabular-nums" data-testid="pantau-kap-maklon">{n(v.load_maklon_pcs)}</TableCell>
                  <TableCell className="text-right tabular-nums font-semibold">{n(v.current_load_pcs)}</TableCell>
                  <TableCell className="text-right tabular-nums">{v.utilization_pct == null ? '—' : pct(v.utilization_pct)}</TableCell>
                  <TableCell className={`text-right tabular-nums ${v.available_pcs < 0 ? 'text-[hsl(var(--danger-text))] font-semibold' : ''}`}>{v.available_pcs == null ? '—' : n(v.available_pcs)}</TableCell>
                  <TableCell className="text-right tabular-nums">{n(v.daily_rate)}</TableCell>
                  <TableCell className="text-right tabular-nums">{!v.current_load_pcs || v.days_to_clear == null ? '—' : `${n(v.days_to_clear)} hari`}</TableCell>
                  <TableCell className="text-right tabular-nums">{n(v.telat_po_count)}</TableCell>
                  <TableCell><Badge meta={CAP_META[v.status]} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
    </PageLayout>
  );
}

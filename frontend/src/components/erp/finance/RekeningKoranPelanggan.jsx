/**
 * Rekening koran pelanggan — popup dari Keuangan › Piutang (tombol "Rekening koran" atau nama pelanggan di daftar).
 *
 * 11 Nov 2026 (owner, Piutang satu daftar tanpa tab): dipindah dari tab "Umur piutang" (ARLifecycleModule) yang
 * dilepas. Isi sama: ringkasan ditagih/dibayar/sisa, umur faktur belum lunas, riwayat faktur & pembayaran
 * (GET /api/rahaza/ar-360/customer/{id}/statement). Pelanggan dipilih di dalam popup; periode bawaan "Semua waktu".
 */
import { useCallback, useEffect, useState } from 'react';
import { Printer, Receipt, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { DetailPanel } from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS, periodFromPreset } from './PeriodPicker';
import { formatDateID, formatRupiah } from '@/lib/format';
import { humanMemo } from '@/lib/financeLabels';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmtRp = (v) => ((v === null || v === undefined || v === '') ? '—' : formatRupiah(v));

// abu = belum jatuh tempo, kuning = perlu perhatian, merah = masalah (PANDUAN_UI G8)
const BUCKET_META = {
  current: { label: 'Belum jatuh tempo', text: 'text-foreground', bar: 'bg-foreground/30' },
  '1_30': { label: '1–30 hari', text: 'text-[hsl(var(--warning-text))]', bar: 'bg-[hsl(var(--warning)/0.6)]' },
  '31_60': { label: '31–60 hari', text: 'text-[hsl(var(--warning-text))]', bar: 'bg-[hsl(var(--warning))]' },
  '61_90': { label: '61–90 hari', text: 'text-[hsl(var(--danger-text))]', bar: 'bg-[hsl(var(--destructive)/0.7)]' },
  '90_plus': { label: 'Lebih dari 90 hari', text: 'text-[hsl(var(--danger-text))]', bar: 'bg-[hsl(var(--destructive))]' },
};

function BucketSpread({ values = {}, total }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-x-6 gap-y-4">
      {Object.entries(BUCKET_META).map(([key, m]) => {
        const val = Number(values[key] || 0);
        const pct = total > 0 ? (val / total) * 100 : 0;
        return (
          <div key={key}>
            <div className="text-xs text-muted-foreground">{m.label}</div>
            <div className={`text-base font-semibold tabular-nums whitespace-nowrap mt-0.5 ${val ? m.text : 'text-muted-foreground'}`}>{fmtRp(val)}</div>
            <div className="text-right text-xs font-medium text-muted-foreground tabular-nums">{pct.toFixed(0)}%</div>
            <div className="h-1 rounded-full bg-foreground/10 mt-1 overflow-hidden">
              <div className={`h-full ${m.bar}`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function RekeningKoranPelanggan({ token, customers = [], customerId, onClose }) {
  const [pilih, setPilih] = useState(customerId || '');
  const [period, setPeriod] = useState(() => periodFromPreset('all'));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!pilih) { setData(null); return; }
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (period.from) params.set('date_from', period.from);
      if (period.to) params.set('date_to', period.to);
      const r = await fetch(`${API}/api/rahaza/ar-360/customer/${pilih}/statement?${params}`,
        { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        toast.error(e.detail || 'Gagal memuat rekening koran');
        setData(null);
        return;
      }
      setData(await r.json());
    } catch (e) {
      toast.error(`Gagal terhubung ke server: ${e.message}`);
    } finally { setLoading(false); }
  }, [pilih, period.from, period.to, token]);
  useEffect(() => { load(); }, [load]);

  const cust = data?.customer || {};
  const txs = data?.transactions || [];
  return (
    <DetailPanel testId="piutang-rekening-koran" onClose={onClose}
      title={data ? `Rekening koran ${cust.name || ''}` : 'Rekening koran pelanggan'}
      description="Ringkasan faktur dan pembayaran satu pelanggan."
      actions={data && <>
        <Button variant="outline" onClick={() => window.print()}><Printer className="w-4 h-4" />Cetak</Button>
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}>
      <div className="flex flex-wrap items-center gap-2">
        <SmartNativeSelect value={pilih} onChange={(e) => setPilih(e.target.value)} className="h-9 w-full sm:w-64"
          aria-label="Pelanggan" data-testid="piutang-rk-pelanggan">
          <option value="">— Pilih pelanggan —</option>
          {customers.map((c) => <option key={c.id} value={c.id}>{c.code ? `${c.code} · ${c.name}` : c.name}</option>)}
        </SmartNativeSelect>
        <PeriodPicker value={period} onChange={setPeriod} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId="piutang-rk-periode" />
      </div>
      {!pilih ? (
        <p className="text-sm text-muted-foreground">Pilih pelanggan untuk melihat rekening korannya.</p>
      ) : loading || !data ? (
        <div className="space-y-2"><Skeleton className="h-6 w-2/3 rounded" /><Skeleton className="h-16 rounded-lg" /></div>
      ) : (
        <>
          <p className="text-sm text-muted-foreground" data-testid="piutang-rk-ringkasan">
            Ditagih <b className="text-foreground tabular-nums">{fmtRp(data.total_billed)}</b> ({data.total_invoices} faktur)
            {' · '}dibayar <b className="text-foreground tabular-nums">{fmtRp(data.total_paid)}</b> ({data.total_payments} pembayaran)
            {' · '}sisa piutang <b className={`tabular-nums ${data.closing_balance > 0 ? 'text-[hsl(var(--warning-text))]' : 'text-foreground'}`}>{fmtRp(data.closing_balance)}</b>
          </p>
          <div className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Umur faktur belum lunas <span className="font-normal text-muted-foreground tabular-nums">· {fmtRp(data.aging_total || 0)}</span></p>
            <BucketSpread values={data.aging_snapshot || {}} total={data.aging_total || 0} />
          </div>
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-foreground">Riwayat transaksi ({txs.length})</p>
            <TombolUnduh namaBerkas={`rekening-koran-${cust.code || cust.name || 'pelanggan'}`} namaLembar="Rekening koran" baris={txs}
              kolom={[
                { label: 'Tanggal', nilai: (t) => formatDateID(t.date) },
                { label: 'Jenis', nilai: (t) => (t.type === 'invoice' ? 'Faktur' : 'Pembayaran') },
                { label: 'Referensi', nilai: (t) => t.reference || '' },
                { label: 'Keterangan', nilai: (t) => humanMemo(t.description) },
                { label: 'Debit', nilai: (t) => Number(t.debit) || 0 },
                { label: 'Kredit', nilai: (t) => Number(t.credit) || 0 },
                { label: 'Saldo', nilai: (t) => Number(t.balance_after) || 0 },
              ]} />
          </div>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Tanggal</TableHead><TableHead>Jenis</TableHead><TableHead>Referensi</TableHead><TableHead>Keterangan</TableHead>
              <TableHead className="text-right">Debit</TableHead><TableHead className="text-right">Kredit</TableHead><TableHead className="text-right">Saldo</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {txs.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={7} className="p-0 [&>div]:py-8">
                    <EmptyState icon={Receipt} title="Belum ada transaksi" description="Faktur dan pembayaran pelanggan ini akan tampil di sini." />
                  </TableCell>
                </TableRow>
              )}
              {txs.map((t, idx) => (
                <TableRow key={idx}>
                  <TableCell className="text-muted-foreground whitespace-nowrap">{formatDateID(t.date)}</TableCell>
                  <TableCell><StatusBadge status={t.type} label={t.type === 'invoice' ? 'Faktur' : 'Pembayaran'} tone={t.type === 'invoice' ? 'info' : 'success'} /></TableCell>
                  <TableCell className="whitespace-nowrap">{t.reference}</TableCell>
                  <TableCell className="text-muted-foreground">{humanMemo(t.description)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{t.debit > 0 ? fmtRp(t.debit) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{t.credit > 0 ? fmtRp(t.credit) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap font-semibold">{fmtRp(t.balance_after)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
            {txs.length > 0 && (
              <TableFooter><TableRow className="font-semibold">
                <TableCell colSpan={4}>Saldo akhir</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(data.total_billed)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(data.total_paid)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(data.closing_balance)}</TableCell>
              </TableRow></TableFooter>
            )}
          </Table>
        </>
      )}
    </DetailPanel>
  );
}

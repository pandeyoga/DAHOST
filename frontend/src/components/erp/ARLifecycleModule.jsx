/**
 * ARLifecycleModule — Umur piutang (Piutang Reseller › Umur piutang)
 * Phase 30 — Order-to-Cash (OTC) Completion
 *
 * Isi:
 *  A) Ringkasan — angka utama + sebaran umur piutang
 *  B) Piutang terbesar / Per pelanggan (penyaring) — tabel per pelanggan
 *  C) Rekening koran pelanggan — dibuka DI HALAMAN di atas tabel (DetailPanel)
 *
 * 2026-11-05 (PANDUAN_UI G1/G4/G13): cetakan PageLayout. Tab Radix di dalam tab hub → pil penyaring;
 * rekening koran pelanggan dulu MENGGANTI seluruh layar (tombol "Kembali") → kini panel di atas tabel;
 * daftar piutang terbesar dulu deret kartu → tabel. Warna hanya token (G8).
 * 2026-11-05: kartu angka = StatTile (`sub`); periode rekening koran = PeriodPicker dengan "Semua waktu"
 * (bawaan, sama dengan perilaku lama); memo server berbahasa Inggris → humanMemo (lib/financeLabels).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  RefreshCw, Search, FileSpreadsheet, Phone, Printer, Receipt, TrendingUp, Users,
} from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import { toast } from 'sonner';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateID, formatRupiah, formatPercent } from '@/lib/format';
import { humanMemo } from '@/lib/financeLabels';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableHeader, TableBody, TableFooter, TableRow, TableHead, TableCell } from '@/components/ui/table';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS, periodFromPreset } from './finance/PeriodPicker';

const API = process.env.REACT_APP_BACKEND_URL;

// ─── Helpers ───────────────────────────────────────────────────────────────
const fmtRp = (v) => (v === null || v === undefined || v === '') ? '—' : formatRupiah(v);
function fmtNum(v) { return Number(v || 0).toLocaleString('id-ID'); }
function fmtPct(v) {
  if (v === null || v === undefined) return '—';
  return formatPercent(v, 1);   // 2026-11-04: koma desimal id-ID (dulu "3.2%")
}

// PANDUAN_UI G8: abu = belum jatuh tempo, kuning = perlu perhatian, merah = masalah. Dulu 5 warna palet.
const BUCKET_META = {
  current:   { label: 'Belum jatuh tempo', text: 'text-foreground',                    bar: 'bg-foreground/30' },
  '1_30':    { label: '1–30 hari',         text: 'text-[hsl(var(--warning-text))]',    bar: 'bg-[hsl(var(--warning)/0.6)]' },
  '31_60':   { label: '31–60 hari',        text: 'text-[hsl(var(--warning-text))]',    bar: 'bg-[hsl(var(--warning))]' },
  '61_90':   { label: '61–90 hari',        text: 'text-[hsl(var(--danger-text))]',     bar: 'bg-[hsl(var(--destructive)/0.7)]' },
  '90_plus': { label: 'Lebih dari 90 hari', text: 'text-[hsl(var(--danger-text))]',    bar: 'bg-[hsl(var(--destructive))]' },
};
const BUCKET_KEYS = Object.keys(BUCKET_META);

/** Sebaran per kelompok umur — angka + bilah persen (tanpa kartu per kelompok). */
function BucketSpread({ values = {}, counts, total }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-x-6 gap-y-4">
      {BUCKET_KEYS.map((key) => {
        const m = BUCKET_META[key];
        const val = Number(values[key] || 0);
        const pct = total > 0 ? (val / total) * 100 : 0;
        return (
          <div key={key}>
            <div className="text-xs text-muted-foreground">{m.label}</div>
            <div className={`text-base font-semibold tabular-nums whitespace-nowrap mt-0.5 ${val ? m.text : 'text-muted-foreground'}`}>{fmtRp(val)}</div>
            <div className="flex items-center justify-between mt-0.5">
              <span className="text-xs text-muted-foreground">{counts ? `${counts[key] || 0} faktur` : ''}</span>
              <span className="text-xs font-medium text-muted-foreground tabular-nums">{pct.toFixed(0)}%</span>
            </div>
            <div className="h-1 rounded-full bg-foreground/10 mt-1.5 overflow-hidden">
              <div className={`h-full transition-[width] duration-500 ${m.bar}`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Rekening koran pelanggan (DetailPanel) ─────────────────────────────
function CustomerStatementPanel({ customerId, headers, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  // Bawaan "Semua waktu" (from/to kosong = semua transaksi, sama dengan perilaku lama).
  const [period, setPeriod] = useState(() => periodFromPreset('all'));
  const dateFrom = period.from;
  const dateTo = period.to;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (dateFrom) params.set('date_from', dateFrom);
      if (dateTo) params.set('date_to', dateTo);
      const r = await fetch(`${API}/api/rahaza/ar-360/customer/${customerId}/statement?${params}`, { headers });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        toast.error(e.detail || 'Gagal memuat rekening koran');
        return;
      }
      setData(await r.json());
    } catch (e) {
      toast.error('Gagal terhubung ke server: ' + e.message);
    } finally {
      setLoading(false);
    }
  }, [customerId, headers, dateFrom, dateTo]);

  useEffect(() => { load(); }, [load]);

  const cust = data?.customer || {};
  const txs = data?.transactions || [];
  const aging = data?.aging_snapshot || {};
  const totalAging = data?.aging_total || 0;
  const info = [cust.code, cust.address, cust.phone || cust.contact_phone, cust.payment_terms && `Termin ${cust.payment_terms}`].filter(Boolean);

  return (
    <DetailPanel
      testId="ar360-statement-panel"
      title={data ? `Rekening koran ${cust.name || ''}` : 'Rekening koran pelanggan'}
      description={data ? (info.length ? (
        <span className="inline-flex items-center gap-1 flex-wrap">
          {(cust.phone || cust.contact_phone) && <Phone className="w-3 h-3" />}{info.join(' · ')}
        </span>
      ) : null) : 'Memuat…'}
      onClose={onClose}
      actions={<>
        <Button variant="outline" onClick={() => window.print()} data-testid="ar360-print"><Printer className="w-4 h-4" />Cetak</Button>
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
    >
      {/* Periode — "Semua waktu" (bawaan) mengirim tanpa date_from/date_to. testId "ar360-date" → kotak tanggal
          tetap "ar360-date-from"/"ar360-date-to" saat "Pilih tanggal". */}
      <PeriodPicker value={period} onChange={setPeriod} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId="ar360-date" />

      {loading || !data ? (
        <div className="space-y-2" data-testid="ar360-statement-skeleton">
          <Skeleton className="h-6 w-2/3 rounded" />
          <Skeleton className="h-16 rounded-lg" />
          <Skeleton className="h-40 rounded-lg" />
        </div>
      ) : (
        <>
          <p className="text-sm text-muted-foreground" data-testid="ar360-statement-summary">
            Ditagih <b className="text-foreground tabular-nums">{fmtRp(data.total_billed)}</b> ({data.total_invoices} faktur)
            {' · '}dibayar <b className="text-foreground tabular-nums">{fmtRp(data.total_paid)}</b> ({data.total_payments} pembayaran)
            {' · '}sisa piutang <b className={`tabular-nums ${data.closing_balance > 0 ? 'text-[hsl(var(--warning-text))]' : 'text-foreground'}`}>{fmtRp(data.closing_balance)}</b>
          </p>

          <div className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Umur faktur belum lunas <span className="font-normal text-muted-foreground tabular-nums">· {fmtRp(totalAging)}</span></p>
            <BucketSpread values={aging} total={totalAging} />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-semibold text-foreground">Riwayat transaksi ({txs.length})</p>
              <TombolUnduh namaBerkas={`rekening-koran-${cust.code || cust.name || 'pelanggan'}`} namaLembar="Rekening koran" baris={txs} testId="ar360-statement-unduh"
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
            {txs.length === 0 ? (
              <EmptyState icon={Receipt} title="Belum ada transaksi" description="Faktur dan pembayaran pelanggan ini akan tampil di sini." />
            ) : (
              <Table className="md:min-w-0">
                <TableHeader>
                  <TableRow>
                    <TableHead>Tanggal</TableHead>
                    <TableHead>Jenis</TableHead>
                    <TableHead>Referensi</TableHead>
                    <TableHead>Keterangan</TableHead>
                    <TableHead className="text-right">Debit</TableHead>
                    <TableHead className="text-right">Kredit</TableHead>
                    <TableHead className="text-right">Saldo</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {txs.map((t, idx) => {
                    const isInvoice = t.type === 'invoice';
                    return (
                      <TableRow key={idx}>
                        <TableCell className="text-muted-foreground whitespace-nowrap">{formatDateID(t.date)}</TableCell>
                        <TableCell>
                          <StatusBadge status={t.type} label={isInvoice ? 'Faktur' : 'Pembayaran'} tone={isInvoice ? 'info' : 'success'} />
                        </TableCell>
                        <TableCell className="whitespace-nowrap">{t.reference}</TableCell>
                        <TableCell className="text-muted-foreground">{humanMemo(t.description)}</TableCell>
                        <TableCell className="text-right tabular-nums whitespace-nowrap">{t.debit > 0 ? fmtRp(t.debit) : '—'}</TableCell>
                        <TableCell className="text-right tabular-nums whitespace-nowrap">{t.credit > 0 ? fmtRp(t.credit) : '—'}</TableCell>
                        <TableCell className="text-right tabular-nums whitespace-nowrap font-semibold">{fmtRp(t.balance_after)}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
                <TableFooter>
                  <TableRow className="font-semibold">
                    <TableCell colSpan={4} className="text-foreground">Saldo akhir</TableCell>
                    <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(data.total_billed)}</TableCell>
                    <TableCell className="text-right tabular-nums whitespace-nowrap">{fmtRp(data.total_paid)}</TableCell>
                    <TableCell className={`text-right tabular-nums whitespace-nowrap ${data.closing_balance > 0 ? 'text-[hsl(var(--warning-text))]' : 'text-foreground'}`}>
                      {fmtRp(data.closing_balance)}
                    </TableCell>
                  </TableRow>
                </TableFooter>
              </Table>
            )}
          </div>
        </>
      )}
    </DetailPanel>
  );
}

// ─── Tabel piutang terbesar ──────────────────────────────────────────────
function TopDebtorsTable({ debtors, search, selectedId, onPickCustomer }) {
  const filtered = useMemo(() => {
    if (!search) return debtors;
    const q = search.toLowerCase();
    return debtors.filter(d =>
      (d.customer_name || '').toLowerCase().includes(q) ||
      (d.customer_code || '').toLowerCase().includes(q)
    );
  }, [debtors, search]);

  if (filtered.length === 0) {
    return (
      <EmptyState
        icon={search ? Search : Users}
        title={search ? 'Tidak ada pelanggan yang cocok' : 'Tidak ada piutang yang belum lunas'}
        description={search ? 'Coba ubah kata kunci pencarian.' : 'Semua piutang pelanggan sudah lunas.'}
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table className="w-full md:min-w-0">
        <TableHeader>
          <TableRow>
            <TableHead className="text-right w-10">#</TableHead>
            <TableHead className="text-left py-2 px-2">Pelanggan</TableHead>
            <TableHead className="text-right py-2 px-2">Faktur</TableHead>
            <TableHead className="text-right py-2 px-2">Terlama terlambat</TableHead>
            <TableHead className="text-right py-2 px-2">Lewat jatuh tempo</TableHead>
            <TableHead className="text-right py-2 px-2">Sisa piutang</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filtered.map((d, idx) => (
            <TableRow key={d.customer_id} className={`border-b border-foreground/5 hover:bg-foreground/[0.03] ${selectedId === d.customer_id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}>
              <TableCell className="py-2 px-2 text-right tabular-nums text-muted-foreground">{idx + 1}</TableCell>
              <TableCell className="py-2 px-2">
                <Button variant="link" size="sm" className="h-auto p-0 font-semibold" onClick={() => onPickCustomer(d)}
                  data-testid={`ar360-debtor-${d.customer_id}`} title="Buka rekening koran pelanggan">
                  {d.customer_name}
                </Button>
                {d.customer_code && <span className="block text-xs text-muted-foreground">{d.customer_code}</span>}
              </TableCell>
              <TableCell className="py-2 px-2 text-right tabular-nums">{d.invoice_count}</TableCell>
              <TableCell className="py-2 px-2 text-right tabular-nums whitespace-nowrap">
                {d.oldest_days_overdue > 0 ? <span className="text-[hsl(var(--warning-text))]">{d.oldest_days_overdue} hari</span> : <span className="text-muted-foreground">—</span>}
              </TableCell>
              <TableCell className="py-2 px-2 text-right tabular-nums whitespace-nowrap">
                {d.overdue_amount > 0 ? <span className="text-[hsl(var(--danger-text))]">{fmtRp(d.overdue_amount)}</span> : <span className="text-muted-foreground">—</span>}
              </TableCell>
              <TableCell className="py-2 px-2 text-right tabular-nums whitespace-nowrap font-semibold text-foreground">{fmtRp(d.outstanding)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ─── Tabel umur per pelanggan ────────────────────────────────────────────
function AgingMatrixTable({ rows, totals, selectedId, onPickCustomer }) {
  if (rows.length === 0) {
    return (
      <EmptyState icon={FileSpreadsheet} title="Belum ada piutang" description="Umur piutang muncul setelah ada faktur penjualan." />
    );
  }
  const cell = (r, key) => (r[key] > 0
    ? <span className={key === 'current' ? 'text-foreground' : BUCKET_META[key].text}>{fmtRp(r[key])}</span>
    : <span className="text-foreground/20">—</span>);
  // 2026-11-06 (Tahap 2): piutang maklon TERJADWAL (PO dikonfirmasi, barang belum dikirim) — belum jatuh
  // tempo dan di luar saldo piutang; ditampilkan terpisah supaya total umur piutang tetap = buku besar.
  const hasSched = rows.some((r) => Number(r.scheduled || 0) > 0);
  return (
    <div className="overflow-x-auto">
      <Table className="w-full md:min-w-0">
        <TableHeader>
          <TableRow>
            <TableHead className="text-left">Pelanggan</TableHead>
            {BUCKET_KEYS.map((k) => <TableHead key={k} className="text-right py-2 px-2 whitespace-nowrap">{BUCKET_META[k].label}</TableHead>)}
            <TableHead className="text-right py-2 px-2 border-l border-foreground/10">Total</TableHead>
            {hasSched && <TableHead className="text-right py-2 px-2 whitespace-nowrap">Terjadwal (belum jatuh tempo)</TableHead>}
            <TableHead className="text-right py-2 px-2">Aksi</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(r => (
            <TableRow key={r.customer_id} className={`border-b border-foreground/5 hover:bg-foreground/[0.03] ${selectedId === r.customer_id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}>
              <TableCell className="py-2 px-2">
                <div className="flex items-center gap-2">
                  <span className="text-foreground font-semibold truncate max-w-[200px]" title={r.customer_name}>{r.customer_name}</span>
                  {r.customer_code && <span className="text-xs text-muted-foreground">{r.customer_code}</span>}
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  {r.count} faktur · terlama {r.oldest_days_overdue} hari
                </div>
              </TableCell>
              {BUCKET_KEYS.map((k) => (
                <TableCell key={k} className={`py-2 px-2 text-right tabular-nums whitespace-nowrap ${k === '90_plus' ? 'font-bold' : ''}`}>{cell(r, k)}</TableCell>
              ))}
              <TableCell className="py-2 px-2 text-right tabular-nums whitespace-nowrap border-l border-foreground/10">
                <span className="text-foreground font-bold">{fmtRp(r.total)}</span>
              </TableCell>
              {hasSched && <TableCell className="py-2 px-2 text-right tabular-nums whitespace-nowrap text-muted-foreground">{Number(r.scheduled || 0) > 0 ? fmtRp(r.scheduled) : '—'}</TableCell>}
              <TableCell className="py-2 px-2 text-right whitespace-nowrap">
                <Button variant="link" size="sm" className="h-auto p-0"
                  data-testid={`ar360-matrix-statement-${r.customer_id}`}
                  onClick={() => onPickCustomer(r)}>
                  {selectedId === r.customer_id ? 'Tutup rekening koran' : 'Rekening koran'}
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
        <TableFooter>
          <TableRow className="border-t-2 border-[var(--glass-border)] font-bold">
            <TableCell className="py-2 px-2 text-foreground">Total ({totals.count || 0} faktur)</TableCell>
            {BUCKET_KEYS.map((k) => (
              <TableCell key={k} className="py-2 px-2 text-right tabular-nums whitespace-nowrap">{fmtRp(totals[k])}</TableCell>
            ))}
            <TableCell className="py-2 px-2 text-right tabular-nums whitespace-nowrap text-foreground border-l border-foreground/10">{fmtRp(totals.total)}</TableCell>
            {hasSched && <TableCell className="py-2 px-2 text-right tabular-nums whitespace-nowrap text-muted-foreground">{fmtRp(totals.scheduled)}</TableCell>}
            <TableCell></TableCell>
          </TableRow>
        </TableFooter>
      </Table>
    </div>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────
export default function ARLifecycleModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [selectedCustomerId, setSelectedCustomerId] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [matrix, setMatrix] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('overview');
  const [search, setSearch] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r1, r2] = await Promise.all([
        fetch(`${API}/api/rahaza/ar-360/dashboard?top_n=20`, { headers }),
        fetch(`${API}/api/rahaza/ar-360/aging`, { headers }),
      ]);
      if (r1.ok) setDashboard(await r1.json());
      if (r2.ok) setMatrix(await r2.json());
    } catch (e) {
      toast.error('Gagal memuat: ' + e.message);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const matrixRows = useMemo(() => {
    if (!matrix?.rows) return [];
    if (!search) return matrix.rows;
    const q = search.toLowerCase();
    return matrix.rows.filter(r =>
      (r.customer_name || '').toLowerCase().includes(q) ||
      (r.customer_code || '').toLowerCase().includes(q)
    );
  }, [matrix, search]);

  const k = dashboard?.kpis || {};
  const buckets = dashboard?.buckets || {};
  const bucketCounts = dashboard?.bucket_counts || {};
  const totalBucket = Object.values(buckets).reduce((s, v) => s + (Number(v) || 0), 0);
  const pick = (d) => setSelectedCustomerId((cur) => (cur === d.customer_id ? null : d.customer_id));

  const filters = (
    <>
      <FilterChips value={tab} onChange={setTab} testId="ar360-tab" ariaLabel="Tampilan" hideWhenEmpty={false}
        options={[
          { key: 'overview', label: 'Piutang terbesar', icon: TrendingUp, count: (dashboard?.top_debtors || []).length },
          { key: 'matrix', label: 'Per pelanggan', icon: FileSpreadsheet, count: (matrix?.rows || []).length },
        ]} />
      <div className="relative w-full sm:w-64">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <GlassInput className="pl-9 h-9" placeholder="Cari nama / kode pelanggan…"
          value={search} onChange={e => setSearch(e.target.value)} data-testid="ar360-search" />
      </div>
    </>
  );

  return (
    <PageLayout
      testId="ar360-page"
      title="Umur Piutang"
      subtitle="Umur piutang per pelanggan, rekening koran pelanggan, dan pelanggan dengan piutang terbesar."
      filters={filters}
      tools={<>
        {tab === 'overview' ? (
          <TombolUnduh namaBerkas="piutang-terbesar" namaLembar="Piutang terbesar" baris={dashboard?.top_debtors || []} testId="ar360-unduh"
            kolom={[
              { label: 'Pelanggan', nilai: (d) => d.customer_name },
              { label: 'Kode', nilai: (d) => d.customer_code || '' },
              { label: 'Faktur', nilai: (d) => Number(d.invoice_count) || 0 },
              { label: 'Terlama terlambat (hari)', nilai: (d) => Number(d.oldest_days_overdue) || 0 },
              { label: 'Lewat jatuh tempo', nilai: (d) => Number(d.overdue_amount) || 0 },
              { label: 'Sisa piutang', nilai: (d) => Number(d.outstanding) || 0 },
            ]} />
        ) : (
          <TombolUnduh namaBerkas="umur-piutang-per-pelanggan" namaLembar="Umur piutang" baris={matrixRows} testId="ar360-unduh"
            kolom={[
              { label: 'Pelanggan', nilai: (r) => r.customer_name },
              { label: 'Kode', nilai: (r) => r.customer_code || '' },
              { label: 'Faktur', nilai: (r) => Number(r.count) || 0 },
              ...BUCKET_KEYS.map((key) => ({ label: BUCKET_META[key].label, nilai: (r) => Number(r[key]) || 0 })),
              { label: 'Total', nilai: (r) => Number(r.total) || 0 },
              { label: 'Terjadwal (belum jatuh tempo)', nilai: (r) => Number(r.scheduled) || 0 },
            ]} />
        )}
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="ar360-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<>
        {/* 2026-11-04: tombol jalankan M-07 (tandai lewat jatuh tempo) pindah ke Adm. Sistem */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatTile label="Sisa piutang" value={fmtRp(k.total_outstanding)} accent={k.total_outstanding ? 'default' : 'muted'}
            sub={`${fmtNum(k.count_open_invoices)} faktur · ${fmtNum(k.total_unique_debtors)} pelanggan${k.scheduled_amount ? ` · terjadwal maklon ${fmtRp(k.scheduled_amount)}` : ''}`} />
          <StatTile label="Lewat jatuh tempo" value={fmtRp(k.total_overdue_amount)} accent={k.total_overdue_amount > 0 ? 'danger' : 'muted'}
            sub={`${k.count_overdue_invoices || 0} faktur · ${fmtPct(k.overdue_pct_of_outstanding)} dari sisa`} />
          <StatTile label="Rata-rata terlambat" value={`${fmtNum(k.avg_days_overdue || 0)} hari`} sub="ditimbang nilai faktur yang terlambat" />
          <StatTile label="Rata-rata hari tertagih" value={k.dso_estimate_days ? `${fmtNum(k.dso_estimate_days)} hari` : '—'}
            accent={k.dso_estimate_days ? 'default' : 'muted'} sub={`Diterima 30 hari: ${fmtRp(k.cash_collected_30d)}`} />
        </div>
        {/* Sebaran umur — di HP disembunyikan (angka totalnya sudah di kartu; rinciannya di tabel Per pelanggan)
            supaya tabel tidak terdorong ke bawah layar. */}
        <GlassCard className="p-4 space-y-2 hidden sm:block" data-testid="ar360-buckets">
          <p className="text-sm font-semibold text-foreground">Sebaran umur piutang</p>
          <BucketSpread values={buckets} counts={bucketCounts} total={totalBucket} />
        </GlassCard>
      </>}
      detail={selectedCustomerId && (
        <CustomerStatementPanel key={selectedCustomerId} customerId={selectedCustomerId} headers={headers}
          onClose={() => setSelectedCustomerId(null)} />
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading && !dashboard && !matrix ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-9 rounded-lg" />)}</div>
        ) : tab === 'overview' ? (
          <TopDebtorsTable debtors={dashboard?.top_debtors || []} search={search} selectedId={selectedCustomerId} onPickCustomer={pick} />
        ) : (
          <AgingMatrixTable rows={matrixRows} totals={matrix?.totals || {}} selectedId={selectedCustomerId} onPickCustomer={pick} />
        )}
      </GlassCard>
    </PageLayout>
  );
}

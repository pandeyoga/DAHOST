import { Fragment, useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { journalSourceLabel } from '@/lib/financeLabels';
import { formatDateID } from '@/lib/format';
import { RefreshCw, FileText, Download } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile, EmptyState } from './moduleAtoms';
import PageLayout, { RowDetail } from './layout/PageLayout';
import JournalLinesInline from './finance/JournalLinesInline';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 });

/**
 * Buku Besar › Mutasi per akun (saldo berjalan satu akun).
 * 2026-11-05 (PANDUAN_UI G1/G6/G7): cetakan PageLayout; periode lewat PeriodPicker (dulu dua kotak tanggal
 * berlabel KAPITAL di atasnya); nomor jurnal & angka tidak dipatah ke 2 baris; tanpa huruf mesin ketik dan
 * warna hijau/biru; tabel tidak lagi bergulir di wadah setinggi 600 px.
 */
export default function RahazaGeneralLedgerModule({ token }) {
  const [accounts, setAccounts] = useState([]);
  const [code, setCode] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [openLine, setOpenLine] = useState(null);
  // Bawaan sama dengan dulu: awal bulan ini s/d hari ini.
  const [period, setPeriod] = useState(() => periodFromPreset('month'));
  const { from, to } = period;
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  useEffect(() => {
    fetch('/api/rahaza/coa/accounts', { headers })
      .then(r => r.ok ? r.json() : [])
      .then(list => { setAccounts(list.filter(a => !a.is_group)); if (list.length > 0) setCode(list.find(a => !a.is_group)?.code || ''); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const fetchGL = useCallback(async () => {
    if (!code) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ account_code: code, from, to });
      const r = await fetch(`/api/rahaza/finance/reports/general-ledger?${params}`, { headers });
      if (r.ok) setData(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, from, to, token]);
  useEffect(() => { fetchGL(); }, [fetchGL]);

  const exportCSV = () => {
    if (!data?.lines) return;
    const rows = data.lines.map(l => [l.date, l.je_number, l.description, journalSourceLabel(l.source), l.debit, l.credit, l.balance]);
    const csv = [
      ['Tanggal', 'Jurnal', 'Keterangan', 'Sumber', 'Debit', 'Kredit', 'Saldo'],
      ...rows,
    ].map(r => r.map(c => typeof c === 'string' && c.includes(',') ? `"${c}"` : c).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `buku-besar-${code}-${from}-${to}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const acc = data?.account;
  const totalDebit = (data?.lines || []).reduce((s, l) => s + (l.debit || 0), 0);
  const totalCredit = (data?.lines || []).reduce((s, l) => s + (l.credit || 0), 0);
  const neg = (n) => (Number(n) < 0 ? 'text-[hsl(var(--destructive))]' : '');

  return (
    <PageLayout
      testId="rahaza-gl-page"
      title="Mutasi per akun"
      subtitle="Semua transaksi satu akun dengan saldo berjalan, dari buku besar."
      filters={<>
        <SmartNativeSelect value={code} onChange={e => setCode(e.target.value)} className="h-9 w-72 max-w-full" aria-label="Akun" data-testid="gl-account">
          <option value="">Pilih akun…</option>
          {accounts.map(a => <option key={a.code} value={a.code}>{`${a.code} · ${a.name}`}</option>)}
        </SmartNativeSelect>
        <PeriodPicker value={period} onChange={setPeriod} testId="gl" />
      </>}
      tools={<>
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchGL} data-testid="gl-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <Button variant="outline" onClick={exportCSV} disabled={!data?.lines?.length} data-testid="gl-export"><Download className="w-4 h-4" />Unduh CSV</Button>
      </>}
      summary={acc && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatTile label="Akun" value={acc.name} testId="gl-kpi-acc" />
          <StatTile label="Saldo awal" value={fmt(data.opening_balance)} testId="gl-kpi-open" />
          <StatTile label="Total debit / kredit" value={`${fmt(totalDebit)} / ${fmt(totalCredit)}`} testId="gl-kpi-mv" />
          <StatTile label="Saldo akhir" value={fmt(data.end_balance)} testId="gl-kpi-end" />
        </div>
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : !data || !data.lines?.length ? (
          <EmptyState icon={FileText}
            title={code ? 'Tidak ada transaksi di periode ini' : 'Pilih akun untuk melihat mutasinya'}
            description={code ? 'Ubah periode atau pilih akun lain.' : 'Mutasi dan saldo berjalan akun tampil di sini.'} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="gl-table">
              <thead>
                <tr>
                  <th className="text-left">Tanggal</th>
                  <th className="text-left">No. jurnal</th>
                  <th className="text-left">Keterangan</th>
                  <th className="text-left">Sumber</th>
                  <th className="text-right">Debit</th>
                  <th className="text-right">Kredit</th>
                  <th className="text-right">Saldo</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-[var(--glass-border)] font-semibold bg-foreground/5">
                  <td colSpan={6}>Saldo awal</td>
                  <td className={`text-right tabular-nums ${neg(data.opening_balance)}`}>{fmt(data.opening_balance)}</td>
                </tr>
                {data.lines.map((l, i) => {
                  const key = l.id || `${l.je_number}-${i}`;
                  const open = openLine === key;
                  return (
                    <Fragment key={key}>
                      <tr className={`border-b border-[var(--glass-border)] hover:bg-foreground/5 ${open ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}>
                        <td className="whitespace-nowrap">{formatDateID(l.date)}</td>
                        <td className="whitespace-nowrap">
                          {/* 2026-11-04 (G13): klik nomor jurnal → isi jurnal di bawah barisnya */}
                          {l.je_id
                            ? <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setOpenLine(open ? null : key)} data-testid={`gl-je-${l.je_number}`}>{l.je_number}</Button>
                            : l.je_number}
                        </td>
                        <td>{l.description || '—'}</td>
                        <td className="text-muted-foreground">{journalSourceLabel(l.source)}</td>
                        <td className="text-right tabular-nums">{l.debit ? fmt(l.debit) : ''}</td>
                        <td className="text-right tabular-nums">{l.credit ? fmt(l.credit) : ''}</td>
                        <td className={`text-right tabular-nums font-semibold ${neg(l.balance)}`}>{fmt(l.balance)}</td>
                      </tr>
                      {open && <RowDetail colSpan={7}><JournalLinesInline jeId={l.je_id} token={token} /></RowDetail>}
                    </Fragment>
                  );
                })}
                <tr className="font-semibold border-t-2 border-[var(--glass-border)]">
                  <td colSpan={4}>Total mutasi</td>
                  <td className="text-right tabular-nums">{fmt(totalDebit)}</td>
                  <td className="text-right tabular-nums">{fmt(totalCredit)}</td>
                  <td className={`text-right tabular-nums ${neg(data.end_balance)}`}>{fmt(data.end_balance)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </PageLayout>
  );
}

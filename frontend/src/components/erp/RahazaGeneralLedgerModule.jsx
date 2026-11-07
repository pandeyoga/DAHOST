import { Fragment, useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { humanMemo, journalSourceLabel } from '@/lib/financeLabels';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatDateID } from '@/lib/format';
import { RefreshCw, FileText } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from './moduleAtoms';
import PageLayout, { RowDetail } from './layout/PageLayout';
import JournalLinesInline from './finance/JournalLinesInline';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import { cvAccountParam, useCv } from '@/lib/entitas';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 });

/**
 * Buku Besar › Mutasi per akun (saldo berjalan satu akun).
 * 2026-11-05 (PANDUAN_UI G1/G6/G7): cetakan PageLayout; periode lewat PeriodPicker (dulu dua kotak tanggal
 * berlabel KAPITAL di atasnya); nomor jurnal & angka tidak dipatah ke 2 baris; tanpa huruf mesin ketik dan
 * warna hijau/biru; tabel tidak lagi bergulir di wadah setinggi 600 px.
 * 2026-11-08 (Standar UI/UX v2): unduh Excel/CSV; 4 kartu (nama akun, saldo awal, debit/kredit, saldo akhir — semuanya
 * sudah ada sebagai baris tabel) diganti satu kalimat; keterangan berbahasa Inggris dari server lewat humanMemo.
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
  const coaCv = cvAccountParam(useCv()?.cv);  // Tahap 8: daftar akun buku CV terpilih (Gabungan = semua)

  useEffect(() => {
    fetch(`/api/rahaza/coa/accounts${coaCv ? `?${coaCv}` : ''}`, { headers })
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

  const acc = data?.account;
  const totalDebit = (data?.lines || []).reduce((s, l) => s + (l.debit || 0), 0);
  const totalCredit = (data?.lines || []).reduce((s, l) => s + (l.credit || 0), 0);
  const neg = (n) => (Number(n) < 0 ? 'text-[hsl(var(--danger-text))]' : '');

  return (
    <PageLayout
      testId="rahaza-gl-page"
      title="Mutasi per akun"
      subtitle="Semua transaksi satu akun dengan saldo berjalan, dari buku besar."
      filters={<>
        <SmartNativeSelect value={code} onChange={e => setCode(e.target.value)} className="h-9 w-full sm:w-64" aria-label="Akun" data-testid="gl-account">
          <option value="">Pilih akun…</option>
          {accounts.map(a => <option key={a.code} value={a.code}>{`${a.code} · ${a.name}`}</option>)}
        </SmartNativeSelect>
        <PeriodPicker value={period} onChange={setPeriod} testId="gl" />
      </>}
      tools={<>
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchGL} data-testid="gl-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <TombolUnduh namaBerkas={`buku-besar-${code}-${from}-${to}`} namaLembar={`Akun ${code}`} baris={data?.lines || []} testId="gl-export"
          kolom={[
            { label: 'Tanggal', nilai: (l) => formatDateID(l.date) },
            { label: 'No. jurnal', nilai: (l) => l.je_number || '' },
            { label: 'Keterangan', nilai: (l) => humanMemo(l.description || '') },
            { label: 'Sumber', nilai: (l) => journalSourceLabel(l.source) },
            { label: 'Debit', nilai: (l) => Number(l.debit) || 0 },
            { label: 'Kredit', nilai: (l) => Number(l.credit) || 0 },
            { label: 'Saldo', nilai: (l) => Number(l.balance) || 0 },
          ]} />
      </>}
      summary={acc && (
        <p className="text-sm text-muted-foreground" data-testid="gl-ringkas">
          <b className="text-foreground" data-testid="gl-kpi-acc">{acc.code ? `${acc.code} · ` : ''}{acc.name}</b>
          {' '}· saldo awal <b className={`tabular-nums ${neg(data.opening_balance) || 'text-foreground'}`} data-testid="gl-kpi-open">{fmt(data.opening_balance)}</b>
          {' '}· debit <b className="text-foreground tabular-nums" data-testid="gl-kpi-mv">{fmt(totalDebit)}</b> · kredit <b className="text-foreground tabular-nums">{fmt(totalCredit)}</b>
          {' '}· saldo akhir <b className={`tabular-nums ${neg(data.end_balance) || 'text-foreground'}`} data-testid="gl-kpi-end">{fmt(data.end_balance)}</b>
        </p>
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
                        <td className="min-w-[12rem]">{humanMemo(l.description) || '—'}</td>
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

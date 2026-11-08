import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Wallet } from 'lucide-react';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import { EmptyState } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateID } from '@/lib/format';
import PeriodPicker, { periodFromPreset } from './finance/PeriodPicker';
import StatementTable, { unduhanLaporan } from './finance/StatementTable';

const fmt = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 });
const COLS = [{ key: 'in', label: 'Masuk' }, { key: 'out', label: 'Keluar' }, { key: 'net', label: 'Bersih' }];

/**
 * Arus Kas › Sudah terjadi.
 * 2026-11-02 (audit No.46 / K19): kedua tampilan dari buku besar — Per akun lawan (OPR/INV/PND) dan
 * Per jenis transaksi (sumber jurnal yang menyentuh kas/bank).
 * 2026-11-04 (PANDUAN_UI G7): satu tabel laporan (Masuk · Keluar · Bersih) — dulu tiap aktivitas satu
 * kartu berwarna, ringkasan berupa kartu besar, dan angka berhuruf mesin ketik hijau/merah.
 * 2026-11-05 (PANDUAN_UI G1): cetakan PageLayout — periode & tampilan di toolbar kiri, muat ulang & unduh di kanan.
 * 2026-11-08 (Standar UI/UX v2): satu tombol Unduh (Excel & CSV, isi = tabel yang tampil) menggantikan dua tombol;
 * 3 kartu (kas awal/perubahan/akhir — sudah ada sebagai baris tabel) diganti satu kalimat; tabel saldo rekening
 * juga bisa diunduh.
 */
export default function RahazaCashFlowModule({ token }) {
  const [view, setView] = useState('account');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [period, setPeriod] = useState(() => periodFromPreset('month'));
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const { from, to } = period;

  const fetchData = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ from, to });
      const r = await fetch(`/api/rahaza/finance/reports/cash-flow?${params}`, { headers });
      if (!r.ok) { setError(`Gagal memuat arus kas (HTTP ${r.status})`); return; }
      setData(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, from, to]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const t = data?.totals || {};
  const ba = data?.by_account;
  const vals = (r) => ({ in: r.inflow || 0, out: r.outflow ? -r.outflow : 0, net: r.net || 0 });
  const sum = (items) => items.reduce((a, r) => ({ in: a.in + (r.inflow || 0), out: a.out - (r.outflow || 0), net: a.net + (r.net || 0) }), { in: 0, out: 0, net: 0 });

  let rows = [];
  let opening = 0; let closing = 0;
  if (data && view === 'account' && ba) {
    opening = ba.totals?.opening_cash_gl; closing = ba.totals?.closing_cash_gl;
    rows = [{ kind: 'line', label: 'Kas awal periode', values: { net: opening } }];
    ['OPR', 'INV', 'PND'].forEach((g) => {
      const grp = ba.groups[g] || { label: g, items: [], total: 0 };
      rows.push({ kind: 'group', id: `acc-${g}`, label: grp.label, values: { ...sum(grp.items), net: grp.total },
        children: grp.items.map((r) => ({ code: r.code, label: r.name, note: r.tag_source === 'default' ? '(kelompok bawaan)' : '', values: vals(r) })) });
    });
    rows.push({ kind: 'subtotal', label: 'Perubahan kas', values: { net: Number(closing || 0) - Number(opening || 0) } });
    rows.push({ kind: 'total', label: 'Kas akhir periode', values: { net: closing }, testId: 'cf-summary' });
  } else if (data) {
    opening = t.opening_cash; closing = t.closing_cash;
    rows = [{ kind: 'line', label: 'Kas awal periode', values: { net: opening } }];
    ['operating', 'investing', 'financing'].forEach((k) => {
      const act = data.activities[k];
      rows.push({ kind: 'group', id: `cat-${k}`, label: act.label, values: { ...sum(act.items), net: act.total },
        children: act.items.map((r) => ({ label: r.label, note: `${r.count} jurnal`, values: vals(r) })) });
    });
    rows.push({ kind: 'subtotal', label: 'Perubahan kas', values: { net: t.net_change_in_cash } });
    rows.push({ kind: 'total', label: 'Kas akhir periode', values: { net: closing }, testId: 'cf-summary' });
  }

  return (
    <PageLayout
      testId="cf-page"
      title="Arus Kas"
      subtitle="Uang masuk dan keluar rekening kas/bank, dari buku besar."
      filters={<>
        <PeriodPicker value={period} onChange={setPeriod} testId="cf-period" />
        <FilterChips value={view} onChange={setView} testId="cf-view" ariaLabel="Tampilan" hideWhenEmpty={false}
          options={[{ key: 'account', label: 'Per kelompok akun' }, { key: 'category', label: 'Per jenis transaksi' }]} />
      </>}
      tools={<>
        <Button variant="outline" size="icon" onClick={fetchData} title="Muat ulang" aria-label="Muat ulang" data-testid="cf-refresh"><RefreshCw className="w-4 h-4" /></Button>
        <TombolUnduh namaBerkas={`arus-kas-${view === 'account' ? 'per-kelompok-akun' : 'per-jenis'}-${from}-${to}`} namaLembar="Arus kas" testId="cf-export"
          baris={unduhanLaporan(COLS, rows, 'Arus kas').baris} kolom={unduhanLaporan(COLS, rows, 'Arus kas').kolom} />
      </>}
      summary={<>
        {error && <p className="text-sm text-[hsl(var(--danger-text))]" data-testid="cf-error">{error}</p>}
        {data && (
          <p className="text-sm text-muted-foreground" data-testid="cf-ringkas">
            Kas awal <b className="text-foreground tabular-nums" data-testid="cf-kpi-open">{fmt(opening)}</b>
            {' '}{Number(closing) < Number(opening) ? '−' : '+'} perubahan <b className={`tabular-nums ${Number(closing) < Number(opening) ? 'text-[hsl(var(--danger-text))]' : 'text-foreground'}`} data-testid="cf-kpi-net">{fmt(Math.abs(Number(closing || 0) - Number(opening || 0)))}</b>
            {' '}= kas akhir <b className="text-foreground tabular-nums" data-testid="cf-kpi-closing">{fmt(closing)}</b>
          </p>
        )}
        {data && view === 'account' && ba && (
          <p className="hidden sm:block text-sm text-muted-foreground" data-testid="cf-ringkas-jurnal">
            {`${ba.totals?.journals || 0} jurnal kas dikelompokkan menurut akun lawan (Operasi / Investasi / Pendanaan di Bagan Akun).`}
          </p>
        )}
        {data && view === 'account' && Math.abs(ba?.totals?.unexplained || 0) > 0.5 && (
          <p className="text-sm text-[hsl(var(--danger-text))]" data-testid="cf-acc-unexplained">
            Selisih {fmt(ba.totals.unexplained)} antara perubahan kas di buku besar dan jumlah per akun lawan — ada jurnal kas ke kas yang tidak seimbang.
          </p>
        )}
      </>}
    >
      {loading ? (
        <Skeleton className="h-80 rounded-[var(--radius-lg)]" />
      ) : !data ? (
        <GlassCard className="p-0">
          <EmptyState icon={Wallet} title="Belum ada arus kas" description="Arus kas muncul setelah ada jurnal yang menyentuh rekening kas/bank." />
        </GlassCard>
      ) : (
        <>
          <StatementTable testId={view === 'account' ? 'cf-by-account' : 'cf-by-category'} columns={COLS} rows={rows}
            labelHeader={`${formatDateID(from)} – ${formatDateID(to)}`} blankZeroChildren />
          {view === 'category' && data.cash_accounts?.length > 0 && (
            <GlassCard className="p-0 overflow-hidden" data-testid="cf-accounts">
              <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-[var(--glass-border)]">
                <p className="font-semibold text-base text-foreground">Saldo rekening kas/bank saat ini</p>
                <TombolUnduh namaBerkas="saldo-rekening-kas-bank" namaLembar="Saldo rekening" baris={data.cash_accounts} testId="cf-accounts-unduh"
                  kolom={[
                    { label: 'Kode', nilai: (a) => a.code },
                    { label: 'Rekening', nilai: (a) => a.name },
                    { label: 'Jenis', nilai: (a) => (a.type === 'bank' ? 'Bank' : 'Kas') },
                    { label: 'Saldo', nilai: (a) => Number(a.balance) || 0 },
                  ]} />
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead><tr><th className="text-left">Rekening</th><th className="text-left">Jenis</th><th className="text-right">Saldo</th></tr></thead>
                  <tbody>
                    {data.cash_accounts.map((a) => (
                      <tr key={a.id}>
                        <td><span className="text-xs text-muted-foreground mr-2">{a.code}</span>{a.name}</td>
                        <td className="text-muted-foreground">{a.type === 'bank' ? 'Bank' : 'Kas'}</td>
                        <td className={`text-right tabular-nums ${Number(a.balance) < 0 ? 'text-[hsl(var(--danger-text))]' : ''}`}>{fmt(a.balance)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          )}
        </>
      )}
    </PageLayout>
  );
}

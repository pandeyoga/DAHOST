/**
 * Peringkat KOL (tab di KOL & Kreator, Portal Toko) — performa kreator dari sesi live.
 *
 * F10 (2026-08-13) — papan peringkat butuh TABEL: rapat mingguan membandingkan kreator baris-per-baris (sesi ·
 * penonton · pesanan/sesi · konversi · omzet). Urutan peringkat TETAP dihitung backend (`rank`) — layar tidak boleh
 * mengurutkan sendiri, kalau tidak lampiran rapat dan layar bisa menunjuk "kreator terbaik" yang BERBEDA.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub), penyaring satu baris, 4 StatTile, tabel +
 * unduh, rincian = DetailPopup (dulu jendela buatan sendiri), tanpa emoji medali, label Indonesia, angka dengan koma.
 * Tampilan "Kartu" diganti tabel (HP: kartu ringkas).
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Trophy } from 'lucide-react';
import apiFetch from '@/lib/apiFetch';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup from '@/components/ui/detail-popup';
import { useToast } from '@/hooks/use-toast';
import { formatRupiah, formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile } from '../moduleAtoms';

const fmtNum = (n) => (n == null ? '—' : new Intl.NumberFormat('id-ID').format(Math.round(n)));
const fmtRp = (n) => (n == null ? '—' : formatRupiah(n));
const desimal = (n, d = 1) => Number(n || 0).toFixed(d).replace('.', ',');

const SORT_OPTIONS = [
  { value: 'conversion_rate', label: 'Konversi tertinggi' },
  { value: 'revenue', label: 'Omzet terbesar' },
  { value: 'viewers', label: 'Penonton terbanyak' },
  { value: 'orders_per_session', label: 'Pesanan per sesi' },
];
const PERIOD_OPTIONS = [
  { value: 7, label: '7 hari terakhir' },
  { value: 14, label: '14 hari terakhir' },
  { value: 30, label: '30 hari terakhir' },
  { value: 90, label: '3 bulan terakhir' },
];

function KOLDetailModal({ kolId, kolName, days, onClose }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch(`/marketing/kol-leaderboard/${kolId}/detail?days=${days}`)
      .then(d => setDetail(d.data))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [kolId, days]);

  const m = detail?.metrics || {};
  const kolomSesi = [
    { kunci: 'tgl', label: 'Tanggal', hp: 'judul', isi: (s) => (s.session_date ? formatDateID(s.session_date) : '—') },
    { kunci: 'penonton', label: 'Penonton', rata: 'kanan', isi: (s) => fmtNum(s.viewers) },
    { kunci: 'pesanan', label: 'Pesanan', rata: 'kanan', isi: (s) => fmtNum(s.orders) },
    { kunci: 'omzet', label: 'Omzet', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmtRp(s.revenue)}</span> },
  ];
  return (
    <DetailPopup open onClose={onClose} judul={kolName} keterangan={`${days} hari terakhir`} testId="kol-detail">
      {loading ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat rincian…</p>
        : !detail ? <p className="py-6 text-center text-sm text-muted-foreground">Data tidak tersedia.</p> : (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
              <StatTile label="Omzet" value={fmtRp(m.total_revenue)} />
              <StatTile label="Penonton" value={fmtNum(m.total_viewers)} />
              <StatTile label="Pesanan" value={fmtNum(m.total_orders)} />
              <StatTile label="Konversi" value={`${desimal(m.conversion_rate, 2)}%`} />
              <StatTile label="Sesi" value={fmtNum(m.session_count)} />
              <StatTile label="Pesanan per sesi" value={desimal(m.orders_per_session)} />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <p className="flex-1 text-sm font-medium">Sesi terakhir · {(detail.sessions || []).length}</p>
              <TombolUnduh namaBerkas={`sesi-kol-${days}-hari`} namaLembar="Sesi" baris={detail.sessions || []} testId="kol-detail-unduh"
                kolom={[{ label: 'Tanggal', nilai: (s) => (s.session_date ? formatDateID(s.session_date) : '') },
                  { label: 'Penonton', nilai: (s) => Number(s.viewers) || 0 }, { label: 'Pesanan', nilai: (s) => Number(s.orders) || 0 },
                  { label: 'Omzet', nilai: (s) => Number(s.revenue) || 0 }]} />
            </div>
            <TabelData kolom={kolomSesi} baris={(detail.sessions || []).slice(0, 10)} kunci={(s) => `${s.session_date}-${s.revenue}-${s.viewers}`}
              testId="kol-detail-sessions" kosong={<EmptyState title="Belum ada sesi pada periode ini" />} />
          </>
        )}
    </DetailPopup>
  );
}

export default function KOLLeaderboardModule() {
  const { toast } = useToast();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);
  const [sortBy, setSortBy] = useState('conversion_rate');
  const [selectedKOL, setSelectedKOL] = useState(null);

  const loadLeaderboard = useCallback(async () => {
    setLoading(true);
    try {
      const result = await apiFetch(`/marketing/kol-leaderboard/?days=${days}&sort_by=${sortBy}`);
      setData(result);
    } catch (err) {
      toast({ title: 'Gagal memuat peringkat', variant: 'destructive' });
      setData({ data: [], metadata: {} });
    } finally {
      setLoading(false);
    }
  }, [days, sortBy, toast]);

  useEffect(() => { loadLeaderboard(); }, [loadLeaderboard]);

  const items = data?.data || [];
  const meta = data?.metadata || {};
  const overall = meta?.overall_stats || {};
  const omzetPerSesi = (k) => (k.session_count ? (k.total_revenue || 0) / k.session_count : 0);

  const kolom = [
    { kunci: 'rank', label: 'Peringkat', rata: 'tengah', isi: (k) => <span className="font-semibold tabular-nums">{k.rank}</span> },
    { kunci: 'nama', label: 'Kreator', hp: 'judul', isi: (k) => <span className="font-medium">{k.kol_name || 'Tanpa nama'}</span> },
    { kunci: 'sesi', label: 'Sesi', rata: 'kanan', isi: (k) => fmtNum(k.session_count) },
    { kunci: 'penonton', label: 'Penonton', rata: 'kanan', isi: (k) => fmtNum(k.total_viewers) },
    { kunci: 'pesanan', label: 'Pesanan', rata: 'kanan', isi: (k) => <span className="tabular-nums">{fmtNum(k.total_orders)}<span className="block text-xs text-muted-foreground">{desimal(k.orders_per_session)} / sesi</span></span> },
    { kunci: 'konversi', label: 'Konversi', rata: 'kanan', isi: (k) => (
      <span className={(k.conversion_rate || 0) >= 1 ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--warning-text))]'}>{desimal(k.conversion_rate, 2)}%</span>) },
    { kunci: 'omzet', label: 'Omzet', rata: 'kanan', isi: (k) => (
      <span className="tabular-nums font-medium md:whitespace-nowrap">{fmtRp(k.total_revenue)}<span className="block text-xs font-normal text-muted-foreground">{fmtRp(omzetPerSesi(k))} / sesi</span></span>) },
  ];

  return (
    <PageLayout testId="kol-leaderboard" title="Peringkat KOL"
      subtitle="Performa kreator dari sesi live: penonton, pesanan per sesi, konversi, omzet."
      filters={<>
        <SmartNativeSelect value={String(days)} onChange={(e) => setDays(Number(e.target.value))} className="w-full" wrapperClassName="w-44 max-w-full" searchable={false} data-testid="kol-period">
          {PERIOD_OPTIONS.map(o => <option key={o.value} value={String(o.value)}>{o.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={sortBy} onChange={(e) => setSortBy(e.target.value)} className="w-full" wrapperClassName="w-48 max-w-full" searchable={false} data-testid="kol-sort">
          {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas={`peringkat-kol-${days}-hari`} namaLembar="Peringkat" baris={items} testId="kol-unduh"
          kolom={[
            { label: 'Peringkat', nilai: (k) => k.rank }, { label: 'Kreator', nilai: (k) => k.kol_name || '' },
            { label: 'Sesi', nilai: (k) => k.session_count || 0 }, { label: 'Penonton', nilai: (k) => k.total_viewers || 0 },
            { label: 'Pesanan', nilai: (k) => k.total_orders || 0 }, { label: 'Pesanan per sesi', nilai: (k) => Number(k.orders_per_session) || 0 },
            { label: 'Konversi (%)', nilai: (k) => Number(k.conversion_rate) || 0 }, { label: 'Omzet', nilai: (k) => k.total_revenue || 0 },
            { label: 'Omzet per sesi', nilai: omzetPerSesi },
          ]} />
        <Button size="icon" variant="outline" onClick={loadLeaderboard} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={items.length > 0 && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="kol-overall">
          <StatTile label="Total omzet" value={fmtRp(overall.total_revenue)} hint={`Semua kreator, ${meta.period_days || days} hari terakhir.`} />
          <StatTile label="Total penonton" value={fmtNum(overall.total_viewers)} />
          <StatTile label="Total pesanan" value={fmtNum(overall.total_orders)} />
          <StatTile label="Rata-rata konversi" value={`${desimal(overall.avg_conversion_rate, 2)}%`} hint="Rata-rata konversi kreator pada periode ini." />
        </div>
      )}>
      {loading && !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat peringkat…</p>
      ) : (
        <TabelData kolom={kolom} baris={items} kunci={(k) => k.kol_id || k.rank} onKlikBaris={setSelectedKOL} testId="kol-table"
          kosong={<EmptyState icon={Trophy} title="Belum ada data sesi live" description="Catat sesi live di Live Selling atau Kelola KOL › Performa live." />} />
      )}

      {selectedKOL && (
        <KOLDetailModal kolId={selectedKOL.kol_id} kolName={selectedKOL.kol_name || 'Kreator'} days={days}
          onClose={() => setSelectedKOL(null)} />
      )}
    </PageLayout>
  );
}

/**
 * PlatformKpiView — **KPI PLATFORM HARIAN** hasil impor ekspor Seller Center (F7.2).
 *
 * Kenapa layar ini ada: sejak F7.2 staf bisa mengunggah ekspor Shopee (statistik
 * toko, Live, Video). Tanpa layar pembaca, angkanya masuk database dan tidak pernah
 * terlihat — persis keluhan yang membuat mesin impor lama dibongkar.
 *
 * Dua aturan angka ditampilkan APA ADANYA di layar, bukan disembunyikan:
 *   1. angka di sini KPI platform (definisi Shopee), BUKAN omzet pesanan;
 *   2. kanal “Toko” sudah mencakup Live + Video — ketiganya tidak boleh dijumlah.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub), periode = PeriodPicker (dulu dua input
 * tanggal bawaan), kanal = StatTile (klik → rincian popup), tabel harian 7 kolom + unduh semua kolom, rincian baris
 * popup. Batas baris dinaikkan 400 → 2000 (maksimum server) + tanda bila terpotong.
 */
import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Info, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { formatRupiah, formatDateID } from '@/lib/format';
import PeriodPicker, { periodFromPreset } from '../finance/PeriodPicker';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { MarketingAccountSelect } from './pickers/MarketingPickers';

const API = process.env.REACT_APP_BACKEND_URL;
const fmtRp = formatRupiah;
const fmtNum = (n) => new Intl.NumberFormat('id-ID').format(Math.round(n || 0));
const pct = (n) => `${Number(n || 0).toFixed(2).replace('.', ',')}%`;
const KANAL = { shop: 'Toko', live: 'Live', video: 'Video' };
const SOURCE_LABEL = {
  shopee_shop_stats: 'Statistik toko',
  shopee_live_1d: 'Live harian',
  shopee_live_overview: 'Live ringkas',
  shopee_video_overview: 'Video ringkas',
};
const BATAS = 2000; // batas maksimum server (dulu 400 → rentang 12 bulan terpotong tanpa tanda)
const tgl = (v) => (v ? formatDateID(String(v).slice(0, 10)) : '—');
const RINCIAN_HARIAN = [
  ['GMV (pesanan dibuat)', 'gmv_created', fmtRp], ['GMV (siap kirim)', 'gmv_ready', fmtRp], ['Pesanan', 'orders_created', fmtNum],
  ['Pengunjung', 'visitors', fmtNum], ['Penonton', 'viewers', fmtNum], ['Ditonton', 'views', fmtNum], ['Suka', 'likes', fmtNum],
  ['Komentar', 'comments', fmtNum], ['Dibagikan', 'shares', fmtNum], ['Pengikut baru', 'new_followers', fmtNum],
  ['Sesi live', 'live_sessions', fmtNum], ['Menit live', 'live_minutes', fmtNum], ['Rata-rata per pesanan', 'aov', fmtRp],
];

export default function PlatformKpiView({ token, onNavigate }) {
  const [accountId, setAccountId] = useState('');
  // Bawaan: bulan ini menurut kalender WIB.
  const [periode, setPeriode] = useState(() => periodFromPreset('month'));
  const from = periode.from;
  const to = periode.to;
  const [summary, setSummary] = useState(null);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [rincian, setRincian] = useState(null);
  const [kanal, setKanal] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ date_from: from, date_to: to });
      if (accountId) qs.set('account_id', accountId);
      const h = { headers: { Authorization: `Bearer ${token}` } };
      const [s, r] = await Promise.all([
        fetch(`${API}/api/marketing/platform-kpi/summary?${qs}`, h),
        fetch(`${API}/api/marketing/platform-kpi?${qs}&limit=${BATAS}`, h),
      ]);
      if (!s.ok) throw new Error(`HTTP ${s.status}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSummary(await s.json());
      setRows(((await r.json())?.rows) || []);
    } catch (e) {
      toast.error(`Gagal memuat KPI platform: ${e.message}`);
      setSummary(null); setRows([]);
    } finally { setLoading(false); }
  }, [accountId, from, to, token]);

  useEffect(() => { load(); }, [load]);

  const channels = summary?.channels || [];
  const keImpor = () => (onNavigate ? onNavigate('marketing-import')
    : toast.info('Buka menu Impor Data untuk mengunggah ekspor Seller Center'));

  const kolom = [
    { kunci: 'tanggal', label: 'Tanggal', hp: 'judul', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{tgl(r.date)}</span> },
    { kunci: 'kanal', label: 'Kanal', isi: (r) => <StatusBadge status={r.channel} label={KANAL[r.channel] || r.channel} tone="muted" /> },
    { kunci: 'sumber', label: 'Sumber', hp: 'keterangan', isi: (r) => <span className="text-muted-foreground md:whitespace-nowrap">{SOURCE_LABEL[r.source] || 'Impor lain'}</span> },
    { kunci: 'gmv', label: 'GMV (dibuat)', rata: 'kanan', isi: (r) => <span className="tabular-nums font-medium md:whitespace-nowrap">{fmtRp(r.gmv_created)}</span> },
    { kunci: 'pesanan', label: 'Pesanan', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtNum(r.orders_created)}</span> },
    { kunci: 'orang', label: 'Pengunjung / penonton', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtNum(r.channel === 'shop' ? r.visitors : r.viewers)}</span> },
    { kunci: 'aov', label: 'Rata-rata per pesanan', rata: 'kanan', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{fmtRp(r.aov)}</span> },
  ];
  const rincianKanal = (c) => [
    ['Hari ber-data', fmtNum(c.days)], ['GMV (pesanan dibuat)', fmtRp(c.gmv_created)], ['Pesanan', fmtNum(c.orders_created)],
    ['Rata-rata per pesanan', fmtRp(c.aov)],
    ...(c.channel === 'shop' ? [
      ['Pengunjung', fmtNum(c.visitors)], ['Konversi', pct(c.conversion_rate)],
      ['Dari live / video', `${fmtRp(c.gmv_live)} / ${fmtRp(c.gmv_video)}`], ['Dari iklan', fmtRp(c.gmv_ads)],
    ] : [
      ['Penonton / ditonton', `${fmtNum(c.viewers)} / ${fmtNum(c.views)}`],
      ['Interaksi', `${fmtNum(c.engagement)} · ${pct(c.engagement_rate)}`], ['Pengikut baru', fmtNum(c.new_followers)],
      ...(c.channel === 'live' ? [['Sesi · menit live', `${fmtNum(c.live_sessions)} · ${fmtNum(c.live_minutes)}`]] : []),
    ]),
  ];

  return (
    <PageLayout testId="platform-kpi-view" title="KPI platform"
      subtitle="KPI harian dari ekspor Seller Center (toko, live, video)."
      actions={<Button onClick={keImpor} data-testid="kpi-goto-import"><Upload />Impor ekspor Shopee</Button>}
      filters={<>
        <MarketingAccountSelect token={token} value={accountId} onChange={setAccountId}
          includeAll allLabel="Semua toko" required={false} label="" testId="kpi-account-select" className="w-56" />
        <PeriodPicker value={periode} onChange={setPeriode} testId="kpi-period" />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="kpi-platform" namaLembar="KPI harian" baris={rows} testId="kpi-unduh"
          kolom={[
            { label: 'Tanggal', nilai: (r) => tgl(r.date) },
            { label: 'Kanal', nilai: (r) => KANAL[r.channel] || r.channel },
            { label: 'Sumber', nilai: (r) => SOURCE_LABEL[r.source] || 'Impor lain' },
            ...RINCIAN_HARIAN.map(([label, k]) => ({ label, nilai: (r) => Number(r[k]) || 0 })),
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="kpi-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={channels.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="kpi-channels">
          {channels.slice(0, 4).map((c) => (
            <StatTile key={c.channel} testId={`kpi-channel-${c.channel}`} label={`${c.label} · GMV pesanan dibuat`}
              value={fmtRp(c.gmv_created)} sub={`${fmtNum(c.orders_created)} pesanan · ${fmtNum(c.days)} hari ber-data`}
              onClick={() => setKanal(c)} hint="Lihat rincian kanal" />
          ))}
        </div>
      )}>
      {loading && !summary ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat KPI platform…</p>
      ) : !channels.length ? (
        <EmptyState testId="kpi-empty" title="Belum ada KPI platform pada periode ini"
          description="Unduh dari Seller Center lalu unggah di menu Impor Data: Statistik toko (.xlsx) → KPI toko Shopee; Live/Video (.csv) → KPI konten Shopee."
          action={<Button onClick={() => onNavigate && onNavigate('marketing-import')} data-testid="kpi-empty-import"><Upload />Buka impor data</Button>} />
      ) : (
        <>
          {rows.length >= BATAS && (
            <Notice tone="warning" title="Daftar terpotong">
              Hanya {fmtNum(BATAS)} baris terbaru yang dimuat{summary?.total_rows ? ` dari ${fmtNum(summary.total_rows)}` : ''}. Persempit periode.
            </Notice>
          )}
          <TabelData kolom={kolom} baris={rows} kunci={(r) => `${r.date}-${r.channel}-${r.source}`} onKlikBaris={setRincian} testId="kpi-table" />
        </>
      )}
      {(summary?.data_notes || []).length > 0 && (
        <Notice tone="info" icon={Info} title="Catatan kejujuran data" testId="kpi-notes">
          <ul className="list-disc space-y-0.5 pl-4">
            {(summary.data_notes || []).map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </Notice>
      )}
      {rincian && (
        <DetailPopup open onClose={() => setRincian(null)} judul={`${KANAL[rincian.channel] || rincian.channel} · ${tgl(rincian.date)}`}
          keterangan={SOURCE_LABEL[rincian.source] || 'Impor lain'} testId="kpi-row-detail">
          <dl className="divide-y divide-[var(--glass-border)]">
            {RINCIAN_HARIAN.map(([label, k, f]) => <BarisDetail key={k} label={label}><span className="tabular-nums">{f(rincian[k])}</span></BarisDetail>)}
          </dl>
        </DetailPopup>
      )}
      {kanal && (
        <DetailPopup open onClose={() => setKanal(null)} judul={`Kanal ${kanal.label}`} keterangan={`${tgl(from)} – ${tgl(to)}`} testId="kpi-channel-detail">
          <dl className="divide-y divide-[var(--glass-border)]">
            {rincianKanal(kanal).map(([l, v]) => <BarisDetail key={l} label={l}><span className="tabular-nums">{v}</span></BarisDetail>)}
          </dl>
        </DetailPopup>
      )}
    </PageLayout>
  );
}

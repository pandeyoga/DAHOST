/**
 * WeeklyMeetingReportModule — LAPORAN RAPAT MINGGUAN (F8).
 *
 * Semua angka datang dari `GET /api/marketing/reports/weekly` — layar ini TIDAK
 * menghitung apa pun. PDF & Excel memakai sumber yang sama, jadi tidak mungkin
 * ada tiga angka berbeda untuk satu minggu.
 *
 * Bagian `catatan_data` (kejujuran data) ditampilkan MENONJOL, bukan di catatan
 * kaki: laporan yang tidak menyebut lubangnya sendiri akan dipakai seolah lengkap.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, DatePicker (dulu input tanggal bawaan), 7 kartu → 4 StatTile + satu
 * kalimat, tabel 21 kolom → 8 kolom + popup rincian per toko (baris gabungan di bawah), kanal = tabel + unduh.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CalendarRange, ChevronLeft, ChevronRight, Download, FileText, RefreshCw,
  Info, TrendingUp, TrendingDown, Minus, Loader2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile } from '../moduleAtoms';
import { toast } from 'sonner';
import { todayWIB, toWIBDate, addDaysISO } from '@/lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL || '';
const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
const num = (n) => Number(n || 0).toLocaleString('id-ID');
// Teks dari server memakai istilah "Settlement" — di layar cukup "Pencairan" (istilah staf).
const bersihkanIstilah = (t) => String(t || '').replace(/Pencairan\s*\/\s*Settlement/gi, 'Pencairan').replace(/\bsettlement\b/gi, 'pencairan');
const pct = (v) => (v === null || v === undefined ? '—' : `${v}%`);

const KANAL = [
  ['live', 'Live'], ['video', 'Video'], ['product_card', 'Kartu Produk'],
  ['ads', 'Iklan'], ['affiliate', 'Afiliasi'], ['campaign', 'Kampanye'],
  ['search', 'Pencarian'], ['organic', 'Organik'], ['other', 'Lainnya'],
];

/** Senin minggu itu menurut KALENDER WIB (lib/waktu), apa pun zona perangkat.
 *  `toISOString()` mengembalikan tanggal UTC — di Asia/Jakarta (UTC+7) sebelum
 *  pukul 07.00 itu masih tanggal SEBELUMNYA, jadi pada hari Senin pagi laporan
 *  yang terbuka adalah MINGGU LALU. Rapat mingguan justru dibuka Senin pagi.
 *  `d` = tanggal 'YYYY-MM-DD' atau instan (Date/ISO). */
function mondayOf(d) {
  const iso = toWIBDate(d);
  if (!iso) return '';
  const [y, m, day] = iso.split('-').map(Number);
  const wd = (new Date(Date.UTC(y, m - 1, day)).getUTCDay() + 6) % 7;   // 0 = Senin
  return addDaysISO(iso, -wd);
}

function Delta({ d }) {
  if (!d) return <span className="text-muted-foreground">—</span>;
  const p = d.persen;
  if (p === null || p === undefined) {
    return <span className="text-xs text-muted-foreground">— (pembanding 0)</span>;
  }
  const Icon = p > 0 ? TrendingUp : p < 0 ? TrendingDown : Minus;
  const tone = p > 0 ? 'text-[hsl(var(--success-text))]' : p < 0 ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground';
  return (
    <span className={`inline-flex items-center gap-1 ${tone} tabular-nums`}>
      <Icon className="w-3 h-3" />{p > 0 ? '+' : ''}{p}%
    </span>
  );
}

export default function WeeklyMeetingReportModule({ token }) {
  const [weekStart, setWeekStart] = useState(() => mondayOf(todayWIB()));
  const [accountId, setAccountId] = useState('');
  const [accounts, setAccounts] = useState([]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [detailToko, setDetailToko] = useState(null);
  const [catatanBuka, setCatatanBuka] = useState(false);

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API}/api/marketing/accounts?status=active`, { headers });
        const b = await r.json().catch(() => ({}));
        setAccounts(Array.isArray(b) ? b : (b.accounts || b.data || []));
      } catch { setAccounts([]); }
    })();
  }, [headers]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ week_start: weekStart });
      if (accountId) qs.set('account_id', accountId);
      const r = await fetch(`${API}/api/marketing/reports/weekly?${qs}`, { headers });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.detail || 'Gagal memuat laporan mingguan');
      setData(b);
    } catch (e) {
      toast.error(e.message, { duration: 9000 });
      setData(null);
    } finally { setLoading(false); }
  }, [headers, weekStart, accountId]);

  useEffect(() => { load(); }, [load]);

  const shift = (days) => setWeekStart(mondayOf(addDaysISO(weekStart, days)));

  const download = async (fmt) => {
    setBusy(fmt);
    try {
      const qs = new URLSearchParams({ week_start: weekStart });
      if (accountId) qs.set('account_id', accountId);
      const r = await fetch(`${API}/api/marketing/reports/weekly/export-${fmt}?${qs}`, { headers });
      if (!r.ok) {
        const b = await r.json().catch(() => ({}));
        throw new Error(b.detail || `Gagal mengunduh ${fmt.toUpperCase()}`);
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `laporan-rapat-mingguan-${data?.periode?.minggu || weekStart}.${fmt === 'pdf' ? 'pdf' : 'xlsx'}`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`${fmt.toUpperCase()} diunduh`);
    } catch (e) {
      toast.error(e.message, { duration: 9000 });
    } finally { setBusy(''); }
  };

  const g = data?.gabungan || {};
  const per = data?.per_toko || [];
  const sumber = (src) => (src === 'orders_auto' ? 'Turunan pesanan' : src === 'manual_override' ? 'Diganti SPV'
    : src === 'import' ? 'Impor rekap' : src === 'manual' ? 'Manual' : 'Lainnya');
  const baris = per.length ? [...per, { account_id: '__gabungan__', account_code: 'Gabungan', account_name: `${g.toko_berdata ?? 0}/${g.toko ?? 0} toko berdata`,
    omzet: g.omzet, nilai_retur: g.nilai_retur, omzet_setelah_retur: g.omzet_setelah_retur, vs_minggu_lalu: g.vs_minggu_lalu,
    pesanan: g.pesanan, pcs: g.pcs, aov: g.aov, pencapaian_target_persen: g.pencapaian_target_persen,
    target: { lengkap: true, revenue: g.target_prorata }, iklan: { terisi: true, spend: g.iklan_spend, roas: g.roas }, _gabungan: true }] : [];
  const [detail, setDetail] = [detailToko, setDetailToko];

  const kolom = [
    { kunci: 'toko', label: 'Toko', hp: 'judul', isi: (s) => (
      <div data-testid={`weekly-row-${s.account_code}`}>
        <p className={s._gabungan ? 'font-semibold' : 'font-medium'}>{s._gabungan ? 'Gabungan' : s.account_name}</p>
        <p className="text-xs text-muted-foreground">{s._gabungan ? s.account_name : s.account_code}</p>
      </div>) },
    { kunci: 'omzet', label: 'Omzet', rata: 'kanan', isi: (s) => <span className="tabular-nums font-semibold md:whitespace-nowrap">{rp(s.omzet)}</span> },
    { kunci: 'retur', label: 'Setelah retur', rata: 'kanan', isi: (s) => (
      <div className="md:whitespace-nowrap" data-testid={`weekly-retur-${s.account_code}`}>
        <p className="tabular-nums">{rp(s.omzet_setelah_retur)}</p>
        {(s.nilai_retur || 0) > 0 && <p className="text-xs text-[hsl(var(--warning-text))]">retur {rp(s.nilai_retur)}</p>}
      </div>) },
    { kunci: 'vs', label: 'vs minggu lalu', rata: 'kanan', isi: (s) => <Delta d={s.vs_minggu_lalu?.omzet} /> },
    { kunci: 'pesanan', label: 'Pesanan', rata: 'kanan', isi: (s) => <span className="tabular-nums">{num(s.pesanan)}</span> },
    { kunci: 'target', label: 'Capai target', rata: 'kanan', isi: (s) => (s.target?.lengkap
      ? <span className="tabular-nums" title={`Target prorata ${rp(s.target.revenue)}`}>{pct(s.pencapaian_target_persen)}</span>
      : <span className="text-muted-foreground">Belum ada target</span>) },
    { kunci: 'iklan', label: 'Iklan', rata: 'kanan', isi: (s) => (s.iklan?.terisi
      ? <span className="tabular-nums md:whitespace-nowrap">{rp(s.iklan.spend)}<span className="block text-xs text-muted-foreground">ROAS {s.iklan.roas ?? '—'}</span></span>
      : <span className="text-muted-foreground">Belum diimpor</span>) },
    { kunci: 'hari', label: 'Hari berdata', rata: 'kanan', isi: (s) => (s._gabungan ? '—' : <span className="tabular-nums">{s.hari_berdata}/7</span>) },
  ];

  const kanalRows = KANAL.map(([k, label]) => ({ k, label, nilai: g.kanal?.[k] || 0, persen: g.kanal_persen?.[k] ?? 0 }));

  return (
    <PageLayout testId="weekly-report-module" title="Laporan rapat mingguan"
      subtitle="Per toko dan gabungan — siap dibacakan, dicetak, dan diarsipkan."
      actions={<>
        <Button variant="outline" onClick={() => download('excel')} disabled={busy === 'excel'} data-testid="weekly-export-excel">
          {busy === 'excel' ? <Loader2 className="animate-spin" /> : <Download />}Unduh Excel
        </Button>
        <Button variant="outline" onClick={() => download('pdf')} disabled={busy === 'pdf'} data-testid="weekly-export-pdf">
          {busy === 'pdf' ? <Loader2 className="animate-spin" /> : <FileText />}Unduh PDF
        </Button>
      </>}
      filters={<>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" onClick={() => shift(-7)} data-testid="weekly-prev" title="Minggu lalu" aria-label="Minggu lalu"><ChevronLeft /></Button>
          <div className="w-44" title="Pilih tanggal apa pun di minggu itu">
            <DatePicker value={weekStart} onChange={(v) => v && setWeekStart(mondayOf(v))} bolehKosong={false} testId="weekly-date" />
          </div>
          <Button variant="outline" size="icon" onClick={() => shift(7)} data-testid="weekly-next" title="Minggu depan" aria-label="Minggu depan"><ChevronRight /></Button>
        </div>
        <SmartNativeSelect className="w-56" value={accountId} onChange={(e) => setAccountId(e.target.value)} data-testid="weekly-account">
          <option value="">Semua toko + gabungan</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </SmartNativeSelect>
        {data?.periode && (
          <span className="text-sm text-muted-foreground" data-testid="weekly-period-label"
            title={`${data.periode.dasar_minggu} · pembanding: ${data.periode.minggu_sebelumnya?.label || '—'}`}>
            {data.periode.minggu} · {data.periode.label}
          </span>
        )}
      </>}
      tools={(
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="weekly-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      )}
      summary={data && (<>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Omzet gabungan" value={rp(g.omzet)} testId="weekly-tile-omzet"
            sub={<>vs minggu lalu <Delta d={g.vs_minggu_lalu?.omzet} /></>} />
          <StatTile label="Pesanan" value={num(g.pesanan)} testId="weekly-tile-pesanan"
            sub={`${num(g.pcs)} pcs · rata-rata ${rp(g.aov)}`} />
          <StatTile label="Capai target prorata" value={pct(g.pencapaian_target_persen)} testId="weekly-tile-target"
            sub={`Target ${rp(g.target_prorata)}`} />
          <StatTile label="Belanja iklan" value={rp(g.iklan_spend)} testId="weekly-tile-iklan"
            sub={`ROAS ${g.roas ?? '—'}`} />
        </div>
        <div className="space-y-0.5 text-sm text-muted-foreground">
          <p data-testid="weekly-tile-setelah-retur">Setelah retur {rp(g.omzet_setelah_retur)}
            {(g.retur || 0) > 0 ? ` (retur ${num(g.retur)} pesanan · ${rp(g.nilai_retur)})` : ' (tidak ada retur minggu ini)'}.</p>
          <p data-testid="weekly-tile-belum-kirim">Belum dikirim {num(g.belum_dikirim)} pesanan ({rp(g.nilai_belum_dikirim)}).</p>
        </div>
      </>)}>
      {loading && !data ? (
        <div className="space-y-2">{[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-12" />)}</div>
      ) : !data ? null : (
        <>
          {(data.catatan_data || []).length > 0 && (
            // Tetap menonjol (warna peringatan, di atas tabel) tetapi ringkas: isi lengkap dibuka satu klik.
            <div className="space-y-1" data-testid="weekly-data-notes">
              <p className="flex flex-wrap items-center gap-1.5 text-sm text-[hsl(var(--warning-text))]">
                <Info className="h-4 w-4 shrink-0" />
                <b>{data.catatan_data.length} catatan kejujuran data — baca sebelum menyimpulkan.</b>
                <Button variant="link" size="sm" className="h-auto p-0 text-sm" onClick={() => setCatatanBuka((v) => !v)}
                  aria-expanded={catatanBuka} data-testid="weekly-data-notes-toggle">
                  {catatanBuka ? 'Sembunyikan' : 'Baca catatan'}
                </Button>
              </p>
              {catatanBuka && (
                <ol className="ml-6 list-decimal space-y-1 text-sm text-muted-foreground">
                  {data.catatan_data.map((n, i) => <li key={i}>{bersihkanIstilah(n)}</li>)}
                </ol>
              )}
            </div>
          )}

          <TabelData kolom={kolom} baris={baris} kunci={(s) => s.account_id} onKlikBaris={(s) => !s._gabungan && setDetail(s)}
            testId="weekly-table"
            kosong={<EmptyState icon={CalendarRange} title="Belum ada data minggu ini" description="Pilih minggu lain atau toko lain." />} />

          <section className="space-y-2" data-testid="weekly-kanal">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-base font-semibold">Pecahan omzet per kanal (gabungan)</p>
              <TombolUnduh namaBerkas={`omzet-per-kanal-${weekStart}`} namaLembar="Per kanal" baris={kanalRows} testId="weekly-kanal-unduh"
                kolom={[{ label: 'Kanal', nilai: (r) => r.label }, { label: 'Omzet', nilai: (r) => Number(r.nilai) }, { label: 'Persen', nilai: (r) => Number(r.persen) }]} />
            </div>
            <TabelData baris={kanalRows} kunci={(r) => r.k} testId="weekly-kanal-table"
              kolom={[
                { kunci: 'kanal', label: 'Kanal', hp: 'judul', isi: (r) => r.label },
                { kunci: 'omzet', label: 'Omzet', rata: 'kanan', isi: (r) => <span className="tabular-nums">{rp(r.nilai)}</span> },
                { kunci: 'persen', label: 'Bagian', rata: 'kanan', isi: (r) => <span className="tabular-nums">{Number(r.persen).toLocaleString('id-ID')}%</span> },
              ]} />
          </section>
        </>
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={detail.account_name} keterangan={`${detail.account_code} · ${data?.periode?.label || ''}`}
          testId="weekly-detail">
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Omzet">{rp(detail.omzet)} <Delta d={detail.vs_minggu_lalu?.omzet} /></BarisDetail>
            <BarisDetail label="Retur">{(detail.nilai_retur || 0) > 0 ? `${rp(detail.nilai_retur)} · ${num(detail.pesanan_mentah?.retur)} pesanan` : '—'}</BarisDetail>
            <BarisDetail label="Setelah retur">{rp(detail.omzet_setelah_retur)}</BarisDetail>
            <BarisDetail label="Pesanan / pcs">{num(detail.pesanan)} pesanan · {num(detail.pcs)} pcs · rata-rata {rp(detail.aov)}</BarisDetail>
            <BarisDetail label="Target prorata">{detail.target?.lengkap ? `${rp(detail.target.revenue)} · capai ${pct(detail.pencapaian_target_persen)}` : 'Belum ada target'}</BarisDetail>
            <BarisDetail label="Kanal">Live {rp(detail.kanal?.live)} · Video {rp(detail.kanal?.video)} · Kartu produk {rp(detail.kanal?.product_card)}</BarisDetail>
            <BarisDetail label="Pemenuhan">{pct(detail.pemenuhan?.fulfillment_rate)} · batal {num(detail.pesanan_mentah?.batal)} · belum kirim {num(detail.pesanan_mentah?.belum_dikirim)}</BarisDetail>
            <BarisDetail label="Iklan">{detail.iklan?.terisi ? `${rp(detail.iklan.spend)} · ROAS ${detail.iklan.roas ?? '—'}` : 'Belum diimpor'}</BarisDetail>
            <BarisDetail label="Hari berdata">{detail.hari_berdata}/7</BarisDetail>
            <BarisDetail label="Sumber angka">{(detail.sumber_angka || []).map(sumber).join(', ') || '—'}</BarisDetail>
          </dl>
        </DetailPopup>
      )}
    </PageLayout>
  );
}

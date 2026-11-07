/**
 * CMTOverrideWeeklyRecap — **Rekap Mingguan** (tab kedua pintu "Input Vendor CMT").
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * PERTANYAAN YANG DIJAWAB LAYAR INI
 * ═══════════════════════════════════════════════════════════════════════════
 * Tab Harian menjawab "siapa yang belum diisi HARI INI". Itu cukup untuk mengejar
 * pekerjaan hari ini, tapi tidak bisa menjawab pertanyaan yang dibawa ke rapat:
 * **"vendor mana yang BELAKANGAN INI sering bolong?"** Satu hari merah bisa
 * kebetulan (vendor libur, listrik mati). Tujuh hari berturut-turut merah adalah
 * masalah — dan karena tagihan CMT dihitung dari progress produksi, masalah itu
 * berujung ke uang yang tidak bisa ditagih.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * KEPUTUSAN OWNER (2026-08-10)
 * ═══════════════════════════════════════════════════════════════════════════
 *  1  Jendela = **7 hari terakhir BERGULIR** (bukan Senin–Minggu ISO).
 *  2  "Terlambat" ditampilkan sebagai **DUA angka terpisah**, tidak ada yang
 *     dibuang: **Terlambat** = hari yang ada pekerjaan menunggu tapi NOL bukti
 *     (merah, dipakai mengurutkan) · **Belum beres** = hari terlambat + hari yang
 *     sudah diisi tapi masih ada sisa (amber).
 *  3  Kolom: 7 kotak hari · terlambat · belum beres · hari tanpa setoran ·
 *     total pcs disetor/dikirim · tren pcs (sparkline) · streak.
 *  4  **Streak** = rentetan hari beruntun paling akhir; putus pada hari terlambat
 *     ATAU belum beres; hari tanpa pekerjaan bersifat netral.
 *  5  Export Excel + PDF · klik kotak hari → buka tab Harian tanggal itu ·
 *     tombol reminder menegur untuk SATU tanggal yang disebut jelas.
 *  6  **F12 — perbandingan antar-pekan** bersifat OPT-IN (tombol "Bandingkan
 *     pekan lalu"): membandingkan berarti backend membangun DUA jendela, dan
 *     gate `INV-REKAP` RK-27 menjaga layar mingguan tidak lebih mahal daripada
 *     7× rekap harian. Panelnya membawa kartu delta ringkasan, papan **vendor
 *     yang bergerak** (urutannya dari backend), kolom "vs pekan lalu" di tabel,
 *     dan filter "hanya yang memburuk". Vendor yang tidak punya pekerjaan di
 *     salah satu pekan TIDAK diperingkat — tapi alasannya ditulis, bukan
 *     dihilangkan diam-diam.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * SEMUA ANGKA DATANG DARI BACKEND — BROWSER TIDAK MENGHITUNG APA PUN
 * ═══════════════════════════════════════════════════════════════════════════
 * `GET /api/cmt-override/weekly-recap` memanggil `build_recap()` untuk tiap hari
 * (SSOT `backend/core/cmt_daily_recap.py`), jadi angka tab ini secara struktural
 * TIDAK BISA berbeda dari tab Harian. Kalau layar ini ikut menjumlah sendiri,
 * suatu hari kartu ringkasan akan berdebat dengan tabelnya sendiri — dan tidak
 * ada yang tahu mana yang benar.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, BellRing, CalendarDays, CheckCircle2, ChevronLeft,
  ChevronRight, Download, FileSpreadsheet, FileText, Flame, GitCompareArrows, Info,
  Loader2, MinusCircle, RefreshCw, Search, TrendingDown, TrendingUp, UserCog, X, XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import DatePicker from '@/components/ui/date-picker';
import { Checkbox } from '@/components/ui/checkbox';
import { ResponsiveTableWrapper } from '@/components/ui/responsive-table-wrapper';
import { apiGet, apiPost, apiFetch } from '../../../lib/api';
import { dayLabel, isoToday, shiftDay as shiftDayUtil } from './recapDates';

// ── Tampilan satu KOTAK HARI ────────────────────────────────────────────────
// Lima keadaan, bukan dua. `future` sengaja dibedakan dari `idle`: hari yang
// belum terjadi BUKAN "tidak ada pekerjaan", dan menyamakannya membuat pembaca
// menyimpulkan vendor sedang kosong padahal harinya belum datang.
const DAY_STYLE = {
  done: {
    Icon: CheckCircle2,
    cls: 'border-[hsl(var(--success)/0.35)] bg-[hsl(var(--success)/0.1)] text-[hsl(var(--success-text))] hover:bg-[hsl(var(--success)/0.15)]',
    label: 'Lengkap',
  },
  partial: {
    Icon: AlertTriangle,
    cls: 'border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.1)] text-[hsl(var(--warning-text))] hover:bg-[hsl(var(--warning)/0.15)]',
    label: 'Masih ada sisa',
  },
  pending: {
    Icon: XCircle,
    cls: 'border-[hsl(var(--destructive)/0.35)] bg-[hsl(var(--destructive)/0.1)] text-[hsl(var(--danger-text))] hover:bg-[hsl(var(--destructive)/0.15)]',
    label: 'Belum diisi',
  },
  idle: {
    Icon: MinusCircle,
    cls: 'border-border bg-muted/40 text-muted-foreground hover:bg-muted/70',
    label: 'Tidak ada pekerjaan',
  },
  future: {
    Icon: MinusCircle,
    cls: 'border-dashed border-border bg-background text-muted-foreground',
    label: 'Belum terjadi',
  },
};

const ROW_STATUS = {
  late: { text: 'Pernah terlambat', cls: 'border-[hsl(var(--destructive)/0.35)] bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--danger-text))]' },
  unfinished: { text: 'Belum beres', cls: 'border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning-text))]' },
  clean: { text: 'Rapi sepekan', cls: 'border-[hsl(var(--success)/0.35)] bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success-text))]' },
  idle: { text: 'Tidak ada pekerjaan', cls: 'border-border bg-muted text-muted-foreground' },
};

// ═════════════════════════════════════════════════════════════════════════════
// PANDUAN_UI G5: kartu angka = StatTile (netral, warna hanya pada angka).
const STAT_ACCENT = { red: 'danger', amber: 'warning', green: 'success', grey: 'muted', blue: 'primary' };
function StatCard({ testid, label, value, tone, hint }) {
  return <StatTile testId={testid} label={label} value={value} accent={STAT_ACCENT[tone] || 'muted'} sub={hint || undefined} />;
}

// ═════════════════════════════════════════════════════════════════════════════
/**
 * Sparkline batang 7 hari — SVG mentah, tanpa pustaka grafik.
 *
 * Alasan: satu baris tabel per vendor bisa berisi puluhan sparkline. Memasang
 * komponen chart penuh (recharts) di setiap baris membuat layar pagi berat tanpa
 * menambah informasi — yang dibutuhkan hanya "hari mana yang tinggi/kosong".
 */
function Sparkline({ values = [], testid, title }) {
  const nums = values.map(v => Number(v) || 0);
  const max = Math.max(1, ...nums);
  const W = 74;
  const H = 24;
  const n = nums.length || 1;
  const bw = W / n;
  const kosong = nums.every(v => v <= 0);
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={title || `Tren pcs per hari: ${nums.join(', ')}`}
      title={title} data-testid={testid} data-values={nums.join(',')}>
      <line x1="0" y1={H - 0.5} x2={W} y2={H - 0.5} stroke="hsl(var(--border))" strokeWidth="1" />
      {nums.map((v, i) => {
        const h = v > 0 ? Math.max(3, (v / max) * (H - 5)) : 1.5;
        return (
          <rect key={i} x={i * bw + 1} y={H - 1 - h} width={Math.max(2.5, bw - 2.5)}
            height={h} rx="1" fill={v > 0 ? 'hsl(var(--primary))' : 'hsl(var(--muted))'} />
        );
      })}
      {kosong && (
        <text x={W / 2} y={H / 2 + 3} textAnchor="middle" fontSize="8" fill="hsl(var(--muted-foreground))">
          tanpa setoran
        </text>
      )}
    </svg>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
function DayBox({ cell, vendorId, onOpen }) {
  const st = DAY_STYLE[cell?.state] || DAY_STYLE.idle;
  const { Icon } = st;
  const qty = Number(cell?.qty_progress || 0);
  const future = cell?.is_future === true;
  const pendingTasks = (cell?.pending_tasks || []).join(', ');
  const tip = future
    ? `${cell?.date} — hari ini belum terjadi`
    : `${cell?.date} — ${st.label}${pendingTasks ? `: ${pendingTasks}` : ''}`
      + (qty ? ` · ${qty} pcs disetor` : '')
      + '\nKlik untuk membuka Rekap Harian tanggal ini';

  const body = (
    <>
      <span className="flex items-center justify-center gap-1">
        <Icon className="h-3.5 w-3.5 flex-shrink-0" />
        {cell?.is_today ? <span className="text-xs font-bold">kini</span> : null}
      </span>
      <span className="mt-0.5 block text-xs font-semibold leading-none">
        {qty > 0 ? `${qty} pcs` : future ? '—' : ''}
      </span>
    </>
  );

  const common = {
    'data-testid': `cmt-week-cell-${vendorId}-${cell?.date}`,
    'data-state': cell?.state || 'idle',
    title: tip,
  };

  if (future) {
    return (
      <div className={`w-full rounded-lg border px-1 py-1.5 text-center ${st.cls}`} {...common}>
        {body}
      </div>
    );
  }
  return (
    <Button type="button" variant="ghost" onClick={() => onOpen(cell?.date)}
      className={`h-auto w-full flex-col gap-0 rounded-lg border px-1 py-1.5 text-center font-normal ${st.cls}`}
      {...common}>
      {body}
    </Button>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
/**
 * Satu angka selisih: `+3` / `-2` / `sama`, warnanya mengikuti KEPUTUSAN backend.
 *
 * `lowerIsBetter` dikirim eksplisit dan tidak ditebak dari nama field: aturan
 * "naik = buruk" untuk hari terlambat sudah diputuskan
 * `core/cmt_daily_recap.py`, dan menuliskannya ulang di sini akan membuat suatu
 * hari layar memberi warna hijau untuk angka yang di export disebut memburuk.
 */
function DeltaNum({ diff, lowerIsBetter, unit = '', testid }) {
  const n = Number(diff) || 0;
  const flat = n === 0;
  const better = lowerIsBetter ? n < 0 : n > 0;
  const Arrow = flat ? MinusCircle : (n > 0 ? TrendingUp : TrendingDown);
  const cls = flat
    ? 'text-muted-foreground'
    : better ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]';
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-bold ${cls}`}
      data-testid={testid} data-diff={n}>
      <Arrow className="h-3 w-3" />
      {flat ? 'sama' : `${n > 0 ? '+' : ''}${n}${unit}`}
    </span>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
/**
 * Satu baris papan "vendor yang bergerak".
 *
 * Menyebut PERPINDAHAN STATUS ("rapi → terlambat") dan bukan cuma "+2", karena
 * kalimat itulah yang bisa langsung ditindaklanjuti di rapat. Barisnya bisa
 * diklik untuk membuka vendor tersebut — daftar yang tidak bisa ditindak hanya
 * jadi hiasan.
 */
function MoverRow({ v, tone, onOpen }) {
  const border = tone === 'worse' ? 'border-[hsl(var(--destructive)/0.35)]' : 'border-[hsl(var(--success)/0.35)]';
  const statusFrom = ROW_STATUS[v.status_prev]?.text || '—';
  const statusTo = ROW_STATUS[v.status_now]?.text || '—';
  return (
    <Button type="button" variant="ghost" onClick={() => onOpen(v)}
      className={`h-auto w-full flex-col items-stretch gap-0 whitespace-normal rounded-md border bg-[var(--card-surface)] px-2 py-1.5 text-left font-normal ${border}`}
      title={`Buka ${v.vendor_name}`}
      data-testid={`cmt-week-mover-${v.vendor_id}`} data-direction={v.direction}>
      <p className="flex items-center justify-between gap-2">
        <span className="truncate text-xs font-bold text-foreground">{v.vendor_name}</span>
        <DeltaNum diff={v.days_late_diff} lowerIsBetter unit=" hari"
          testid={`cmt-week-mover-late-${v.vendor_id}`} />
      </p>
      <p className="mt-0.5 flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="truncate">{statusFrom} → <b className="text-foreground">{statusTo}</b></span>
        <DeltaNum diff={v.qty_diff} unit=" pcs"
          testid={`cmt-week-mover-qty-${v.vendor_id}`} />
      </p>
      <p className="mt-0.5 text-xs text-muted-foreground">
        terlambat {v.days_late_prev} → <b className="text-foreground">{v.days_late_now}</b> hari
        {' · '}pcs {v.qty_prev} → <b className="text-foreground">{v.qty_now}</b>
      </p>
    </Button>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Angka pembanding pekan ini vs pekan lalu (kartu delta).
const DELTA_METRICS = [
  { key: 'qty_progress_total', label: 'Pcs disetor' },
  { key: 'qty_shipped_total', label: 'Pcs dikirim' },
  { key: 'days_late_total', label: 'Hari terlambat' },
  { key: 'days_unfinished_total', label: 'Hari belum beres' },
  { key: 'vendors_late', label: 'Vendor terlambat' },
];

export default function CMTOverrideWeeklyRecap({
  endDay, onEndDayChange, onOpenDay, onOpenVendor, canFill = true, viewSwitch = null,
}) {
  const [dayLocal, setDayLocal] = useState(isoToday);
  const controlled = typeof endDay === 'string' && !!endDay;
  const end = controlled ? endDay : dayLocal;

  const setEnd = useCallback((next) => {
    const val = typeof next === 'function' ? next(end) : next;
    if (typeof onEndDayChange === 'function') onEndDayChange(val);
    if (!controlled) setDayLocal(val);
  }, [controlled, end, onEndDayChange]);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [onlyProblem, setOnlyProblem] = useState(false);
  const [onlyWorse, setOnlyWorse] = useState(false);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState('');
  const [confirmRemind, setConfirmRemind] = useState(false);
  // F12 — panel perbandingan antar-pekan. SENGAJA opt-in (tidak menyala sendiri):
  // membandingkan berarti backend membangun DUA jendela, dan gate INV-REKAP RK-27
  // menjaga layar mingguan tidak lebih mahal daripada 7× rekap harian. Jadi
  // biayanya hanya dibayar ketika seseorang benar-benar ingin melihatnya.
  const [compare, setCompare] = useState(false);

  const load = useCallback(async (e, withCompare) => {
    setLoading(true); setErr('');
    try {
      const res = await apiGet(
        `/cmt-override/weekly-recap?date=${e}${withCompare ? '&compare=true' : ''}`);
      setData(res);
    } catch (ex) {
      setErr(ex.message || 'Gagal memuat rekap mingguan');
      setData(null);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(end, compare); }, [end, compare, load]);

  const days = useMemo(() => data?.days || [], [data]);
  const perDay = useMemo(() => data?.per_day || [], [data]);
  const rows = useMemo(() => data?.rows || [], [data]);
  const summary = data?.summary || {};
  const comparison = data?.comparison || null;
  const remindPending = useMemo(() => data?.remind_pending || [], [data]);
  const isCurrent = data?.is_current === true;

  // Peta ringkasan per hari untuk badge di kepala kolom (angka backend, bukan
  // hitungan browser) — supaya kelihatan HARI MANA yang paling banyak bolong.
  const perDayMap = useMemo(() => {
    const m = {};
    perDay.forEach(p => { m[p.date] = p; });
    return m;
  }, [perDay]);

  // Peta perbandingan per vendor — dipakai kolom "vs pekan lalu" di tabel.
  // Isinya HANYA angka dari backend; layar tidak menghitung selisih sendiri,
  // supaya kolom tabel dan papan "vendor yang bergerak" mustahil berbeda.
  const cmpByVendor = useMemo(() => {
    const m = {};
    (comparison?.per_vendor || []).forEach(v => { m[v.vendor_id] = v; });
    return m;
  }, [comparison]);

  const movers = comparison?.movers || null;

  // Kolom "vs pekan lalu" hanya ada kalau datanya benar-benar ada. Menampilkan
  // kolom kosong lebih buruk daripada tidak menampilkannya: kolom yang selalu
  // "—" mengajari pembaca untuk mengabaikannya.
  const showCompareCol = compare && !!comparison && (comparison.per_vendor || []).length > 0;

  // Filter "hanya yang memburuk" hanya masuk akal saat perbandingan menyala.
  // Kalau panelnya ditutup, filternya ikut dilepas — kalau tidak, tabel akan
  // tampak kosong tanpa sebab yang terlihat di layar.
  useEffect(() => { if (!compare) setOnlyWorse(false); }, [compare]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter(r => {
      if (onlyProblem && r.status !== 'late' && r.status !== 'unfinished') return false;
      if (onlyWorse && (cmpByVendor[r.vendor_id]?.direction !== 'worse')) return false;
      if (!q) return true;
      return `${r.vendor_name} ${r.vendor_code} ${r.contact_name}`.toLowerCase().includes(q);
    });
  }, [rows, onlyProblem, onlyWorse, cmpByVendor, search]);

  const download = async (fmt) => {
    setBusy(fmt);
    try {
      // Lampirannya mengikuti apa yang SEDANG DILIHAT: kalau panel perbandingan
      // terbuka, Excel/PDF ikut membawa bagian perbandingan. Legenda di bawah
      // layar menjanjikan "isinya sama dengan layar ini", dan yang dibawa ke
      // rapat justru lampirannya.
      const res = await apiFetch(
        `/cmt-override/weekly-recap/export?format=${fmt}&date=${end}`
        + (compare ? '&compare=true' : ''));
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const guess = (cd.match(/filename="?([^";]+)"?/) || [])[1];
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = guess || `rekap-mingguan-cmt-${end}.${fmt}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(`Rekap mingguan ${fmt.toUpperCase()} diunduh (${data?.start} … ${data?.end}).`);
    } catch (e) {
      toast.error(e.message || 'Gagal mengunduh rekap mingguan');
    } finally { setBusy(''); }
  };

  // Reminder memakai endpoint HARIAN dengan tanggal yang DISEBUT JELAS: reminder
  // tersimpan per vendor per tanggal (idempoten), jadi "tegur untuk 7 hari" tidak
  // punya tanggal yang bisa dipertanggungjawabkan.
  const sendReminders = async () => {
    const tgl = data?.remind_date;
    if (!tgl) return;
    setBusy('remind');
    try {
      const res = await apiPost('/cmt-override/daily-recap/remind', { date: tgl });
      const sent = res?.sent_count || 0;
      const skipped = res?.skipped_count || 0;
      if (sent > 0) {
        toast.success(
          `Reminder terkirim ke ${sent} vendor untuk tanggal ${tgl}.`
          + (skipped ? ` ${skipped} dilewati (sudah ditegur untuk tanggal ini).` : ''),
        );
      } else if (skipped > 0) {
        toast.info(`Tidak ada yang dikirim — ${skipped} vendor sudah ditegur untuk ${tgl}.`);
      } else {
        toast.info('Tidak ada vendor yang perlu ditegur.');
      }
      setConfirmRemind(false);
      // `compare` WAJIB diteruskan. Tanpa ini, memuat ulang setelah mengirim
      // reminder menjawab TANPA blok perbandingan, sehingga panel yang sedang
      // dibuka hilang sendiri tepat setelah staf menekan tombol — kelihatan
      // seperti fiturnya rusak, padahal cuma parameternya jatuh.
      load(end, compare);
    } catch (e) {
      toast.error(e.message || 'Gagal mengirim reminder');
    } finally { setBusy(''); }
  };

  const openDay = (iso) => {
    if (!iso) return;
    if (typeof onOpenDay === 'function') onOpenDay(iso);
    else setEnd(iso);
  };

  const openVendor = (row) => {
    if (typeof onOpenVendor === 'function') onOpenVendor(row, null);
  };

  return (
    <GlassCard data-testid="cmt-week-panel">
      {/* ── Kepala ───────────────────────────────────────────────────────── */}
      <div className="border-b border-border p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div>
              {viewSwitch || <p className="text-base font-semibold text-foreground">Rekap mingguan</p>}
              <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">
                Vendor mana yang <b>sering bolong</b> dalam 7 hari terakhir — satu kotak
                per hari. Klik kotak hari untuk membuka <b>Rekap Harian</b> tanggal itu.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1">
              <Button type="button" variant="outline" size="icon"
                onClick={() => setEnd(d => shiftDayUtil(d, -7))}
                title="7 hari sebelumnya" aria-label="7 hari sebelumnya" data-testid="cmt-week-prev">
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <div className="w-44" title="Hari terakhir jendela 7 hari">
                <DatePicker value={end} max={shiftDayUtil(isoToday(), 1)} bolehKosong={false}
                  onChange={(v) => v && setEnd(v)} testId="cmt-week-date-input" />
              </div>
              <Button type="button" variant="outline" size="icon"
                onClick={() => setEnd(d => shiftDayUtil(d, 7))}
                title="7 hari berikutnya" aria-label="7 hari berikutnya" data-testid="cmt-week-next">
                <ChevronRight className="h-4 w-4" />
              </Button>
              {!isCurrent && (
                <Button type="button" variant="link" size="sm"
                  onClick={() => setEnd(isoToday())} data-testid="cmt-week-today">
                  7 hari terakhir
                </Button>
              )}
            </div>

            <Button type="button" variant="outline" size="icon" onClick={() => load(end, compare)} data-testid="cmt-week-refresh"
              title="Muat ulang" aria-label="Muat ulang">
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
            <Button type="button" variant={compare ? 'default' : 'outline'} size="sm"
              onClick={() => setCompare(v => !v)} data-testid="cmt-week-compare-toggle"
              title="Bandingkan jendela ini dengan 7 hari sebelumnya">
              <GitCompareArrows className="mr-1.5 h-3.5 w-3.5" />
              {compare ? 'Sembunyikan perbandingan' : 'Bandingkan pekan lalu'}
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => download('xlsx')}
              disabled={busy === 'xlsx'} data-testid="cmt-week-export-xlsx">
              {busy === 'xlsx'
                ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                : <FileSpreadsheet className="mr-1.5 h-3.5 w-3.5" />}
              Excel
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => download('pdf')}
              disabled={busy === 'pdf'} data-testid="cmt-week-export-pdf">
              {busy === 'pdf'
                ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                : <FileText className="mr-1.5 h-3.5 w-3.5" />}
              PDF
            </Button>
          </div>
        </div>

        <p className="mt-3 text-xs font-medium text-foreground" data-testid="cmt-week-range-label">
          {data ? `${dayLabel(data.start)} — ${dayLabel(data.end)}` : '…'}
          {isCurrent
            ? <span className="ml-2 inline-flex"><StatusBadge status="current" tone="primary" label="7 hari terakhir" /></span>
            : <span className="ml-2 inline-flex"><StatusBadge status="other" tone="muted" label="Jendela lain" /></span>}
          {summary.days_elapsed < summary.days && (
            <span className="ml-2 inline-flex"><StatusBadge status="future" tone="warning" label={`${summary.days - summary.days_elapsed} hari belum terjadi`} /></span>
          )}
        </p>

        {/* ── Kartu ringkasan ─────────────────────────────────────────────── */}
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <StatCard testid="cmt-week-summary-late" tone="red" label="Pernah terlambat"
            value={summary.vendors_late ?? 0} hint="ada hari nol bukti" />
          <StatCard testid="cmt-week-summary-unfinished" tone="amber" label="Belum beres"
            value={summary.vendors_unfinished ?? 0} hint="terisi, masih ada sisa" />
          <StatCard testid="cmt-week-summary-clean" tone="green" label="Rapi sepekan"
            value={summary.vendors_clean ?? 0} hint="tanpa hari bolong" />
          <StatCard testid="cmt-week-summary-idle" tone="grey" label="Tanpa pekerjaan"
            value={summary.vendors_idle ?? 0} hint="tidak perlu diisi" />
          <StatCard testid="cmt-week-summary-days-late" tone="blue" label="Total hari terlambat"
            value={summary.days_late_total ?? 0}
            hint={`${summary.days_no_progress_total ?? 0} hari tanpa setoran`} />
          <StatCard testid="cmt-week-summary-qty" tone="blue" label="Pcs disetor sepekan"
            value={summary.qty_progress_total ?? 0}
            hint={`${summary.qty_shipped_total ?? 0} pcs dikirim`} />
        </div>

        {/* ── F12 — PERBANDINGAN DENGAN PEKAN SEBELUMNYA ───────────────────────
            Kenapa ada: "5 hari terlambat" tidak berarti apa-apa sendirian.
            Yang dibawa ke rapat adalah arahnya — membaik atau memburuk. Angkanya
            datang dari backend (`build_week()` dipanggil dua kali dengan ctx yang
            sama), jadi tidak mungkin berbeda dari kotak hariannya.
            Kejujuran: kalau pekan berjalan belum lengkap, banner mengatakannya dan
            kolom "per hari" dipakai supaya perbandingannya adil. */}
        {compare && comparison && (
          <Notice tone="info" className="mt-3"
            testId="cmt-week-comparison">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-semibold text-[hsl(var(--primary))]">
                Dibandingkan pekan sebelumnya
                <span className="ml-1 font-normal opacity-80">
                  ({dayLabel(comparison.previous?.start)} — {dayLabel(comparison.previous?.end)})
                </span>
              </p>
              {!comparison.comparable && (
                <span className="rounded-full bg-[hsl(var(--warning)/0.15)] px-2 py-0.5 text-xs font-bold text-[hsl(var(--warning-text))]"
                  data-testid="cmt-week-comparison-not-comparable">
                  belum sebanding
                </span>
              )}
            </div>
            <p className="mt-1 text-xs leading-snug text-[hsl(var(--primary)/0.8)]"
              data-testid="cmt-week-comparison-note">{comparison.note}</p>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {DELTA_METRICS.map(({ key, label }) => {
                const d = comparison.delta?.[key];
                if (!d) return null;
                const flat = Math.abs(d.diff) < 0.005;
                const tone = flat
                  ? 'border-border bg-card text-muted-foreground'
                  : (d.better
                    ? 'border-[hsl(var(--success)/0.35)] bg-[hsl(var(--success)/0.1)] text-[hsl(var(--success-text))]'
                    : 'border-[hsl(var(--destructive)/0.35)] bg-[hsl(var(--destructive)/0.1)] text-[hsl(var(--danger-text))]');
                const Arrow = flat ? MinusCircle : (d.diff > 0 ? TrendingUp : TrendingDown);
                return (
                  <div key={key} className={`rounded-md border p-2 ${tone}`}
                    data-testid={`cmt-week-delta-${key}`}>
                    <p className="text-xs font-medium leading-tight">{label}</p>
                    <p className="mt-0.5 flex items-baseline gap-1 text-lg font-bold leading-none">
                      {d.now}
                      <span className="inline-flex items-center gap-0.5 text-xs font-semibold">
                        <Arrow className="h-3 w-3" />
                        {flat ? 'sama' : `${d.diff > 0 ? '+' : ''}${d.diff}`}
                      </span>
                    </p>
                    <p className="mt-1 text-xs opacity-80">
                      pekan lalu {d.prev}
                      {!comparison.comparable && (
                        <> · per hari {d.now_per_day} vs {d.prev_per_day}</>
                      )}
                    </p>
                  </div>
                );
              })}
            </div>

            {/* ── Papan "VENDOR YANG BERGERAK" ───────────────────────────────
                Kenapa ada: kartu delta di atas menjawab "arahnya ke mana",
                dan pertanyaan berikutnya di rapat SELALU "vendor mana".
                Urutannya datang dari backend (`movers`), bukan diurutkan di
                browser — supaya Excel/PDF yang dibawa ke rapat menunjuk vendor
                terburuk yang SAMA. */}
            {movers && (
              <div className="mt-3 border-t border-[hsl(var(--primary)/0.35)] pt-2.5" data-testid="cmt-week-movers">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs font-semibold text-[hsl(var(--primary))]">Vendor yang bergerak</p>
                  <p className="text-xs text-[hsl(var(--primary)/0.8)]" data-testid="cmt-week-movers-counts">
                    memburuk <b>{movers.counts?.worsened ?? 0}</b>
                    {' · '}membaik <b>{movers.counts?.improved ?? 0}</b>
                    {' · '}sama <b>{movers.counts?.flat ?? 0}</b>
                    {' · '}tidak diperingkat <b>{movers.counts?.incomparable ?? 0}</b>
                    {' dari '}{movers.counts?.vendors ?? 0} vendor
                  </p>
                </div>
                <div className="mt-2 grid gap-2 lg:grid-cols-2">
                  <div data-testid="cmt-week-movers-worsened">
                    <p className="mb-1 flex items-center gap-1 text-xs font-bold text-[hsl(var(--danger-text))]">
                      <TrendingDown className="h-3 w-3" /> Paling memburuk
                    </p>
                    {(movers.worsened || []).length === 0 ? (
                      <EmptyState icon={TrendingDown} className="py-4"
                        title="Tidak ada vendor yang memburuk"
                        description="Semua vendor sama atau lebih baik dibanding pekan lalu." />
                    ) : (
                      <div className="space-y-1.5">
                        {movers.worsened.map(v => (
                          <MoverRow key={v.vendor_id} v={v} tone="worse" onOpen={openVendor} />
                        ))}
                      </div>
                    )}
                  </div>
                  <div data-testid="cmt-week-movers-improved">
                    <p className="mb-1 flex items-center gap-1 text-xs font-bold text-[hsl(var(--success-text))]">
                      <TrendingUp className="h-3 w-3" /> Paling membaik
                    </p>
                    {(movers.improved || []).length === 0 ? (
                      <EmptyState icon={TrendingUp} className="py-4"
                        title="Belum ada vendor yang membaik"
                        description="Vendor yang lebih rapi dibanding pekan lalu akan muncul di sini." />
                    ) : (
                      <div className="space-y-1.5">
                        {movers.improved.map(v => (
                          <MoverRow key={v.vendor_id} v={v} tone="better" onOpen={openVendor} />
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <p className="mt-2 text-xs leading-snug text-[hsl(var(--primary)/0.7)]"
                  data-testid="cmt-week-movers-rule">
                  {movers.rule}
                </p>
                {(movers.counts?.incomparable ?? 0) > 0 && (
                  <p className="mt-1 text-xs leading-snug text-[hsl(var(--warning-text))]"
                    data-testid="cmt-week-movers-excluded">
                    {movers.counts.incomparable} vendor tidak diperingkat karena tidak punya
                    pekerjaan di salah satu pekan
                    {(movers.counts?.new ?? 0) > 0
                      ? ` (termasuk ${movers.counts.new} vendor baru)`
                      : ''}
                    {' '}— mereka tetap tampil di tabel di bawah, lengkap dengan alasannya.
                  </p>
                )}
              </div>
            )}
          </Notice>
        )}
      </div>

      {/* ── Bar aksi ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-muted/30 px-4 py-3">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Cari vendor di rekap mingguan…" className="h-9 pl-9"
            data-testid="cmt-week-search" />
        </div>
        <label className="flex cursor-pointer select-none items-center gap-2 text-xs font-medium text-foreground">
          <Checkbox checked={onlyProblem} onCheckedChange={(v) => setOnlyProblem(!!v)} data-testid="cmt-week-filter-problem" />
          Hanya yang bermasalah
        </label>
        {/* Filter ini hanya muncul saat perbandingan menyala: tanpa data pekan
            lalu, "memburuk" tidak punya arti dan kotaknya cuma akan mengosongkan
            tabel tanpa alasan yang terlihat. */}
        {compare && comparison && (
          <label className="flex cursor-pointer select-none items-center gap-2 rounded-md border border-[hsl(var(--destructive)/0.35)] bg-[hsl(var(--destructive)/0.1)] px-2 py-1 text-xs font-medium text-[hsl(var(--danger-text))]">
            <Checkbox checked={onlyWorse} onCheckedChange={(v) => setOnlyWorse(!!v)} data-testid="cmt-week-filter-worse" />
            Hanya yang memburuk ({movers?.counts?.worsened ?? 0})
          </label>
        )}
        <Button type="button" size="sm" onClick={() => setConfirmRemind(true)}
          disabled={remindPending.length === 0 || busy === 'remind'}
          className="bg-[hsl(var(--warning))] text-white hover:bg-[hsl(var(--warning)/0.9)]"
          title={data?.remind_date
            ? `Menegur untuk tanggal ${data.remind_date} (hari terakhir yang sudah berjalan)`
            : 'Belum ada tanggal yang bisa ditegur'}
          data-testid="cmt-week-remind">
          <BellRing className="mr-1.5 h-3.5 w-3.5" />
          Kirim reminder ({remindPending.length})
        </Button>
      </div>

      {/* ── Konfirmasi reminder: tanggalnya WAJIB disebut ─────────────────── */}
      {confirmRemind && (
        <div className="border-b border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.1)] p-4" data-testid="cmt-week-remind-confirm">
          <div className="flex items-start gap-3">
            <BellRing className="mt-0.5 h-5 w-5 flex-shrink-0 text-[hsl(var(--warning-text))]" />
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-[hsl(var(--warning-text))]">
                Kirim reminder ke {remindPending.length} vendor untuk tanggal{' '}
                <span data-testid="cmt-week-remind-date">{data?.remind_date}</span>?
              </p>
              <p className="mt-1 text-xs text-[hsl(var(--warning-text))]">
                Reminder selalu menempel pada <b>satu tanggal</b> (hari terakhir yang sudah
                berjalan di jendela ini), bukan pada rentang 7 hari — supaya vendor tahu
                data hari mana yang diminta. Satu vendor hanya menerima satu reminder rekap
                per tanggal: klik dua kali tidak menggandakan.
              </p>
              <ul className="mt-2 max-h-32 space-y-1 overflow-y-auto text-xs text-[hsl(var(--warning-text))]">
                {remindPending.map(r => (
                  <li key={r.vendor_id}>
                    • <b>{r.vendor_name}</b>
                    <span className="opacity-80"> — {(r.pending_tasks || []).join(', ')}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-3 flex gap-2">
                <Button type="button" size="sm" onClick={sendReminders} disabled={busy === 'remind'}
                  className="bg-[hsl(var(--warning))] text-white hover:bg-[hsl(var(--warning)/0.9)]"
                  data-testid="cmt-week-remind-confirm-yes">
                  {busy === 'remind' && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
                  Ya, kirim sekarang
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={() => setConfirmRemind(false)}
                  data-testid="cmt-week-remind-confirm-no">
                  Batal
                </Button>
              </div>
            </div>
            <Button type="button" size="icon-sm" variant="ghost"
              onClick={() => setConfirmRemind(false)} title="Tutup" aria-label="Tutup">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      {/* ── Job WARISAN tanpa stempel waktu tutup (fase 5 `closed_at`) ───── */}
      {/* Angka & kalimatnya DIAMBIL dari rekap harian (tab ini tidak menghitung
          apa pun sendiri). Tampil di sini juga karena jendela 7 hari justru yang
          paling terpengaruh: satu job warisan bisa membuat beberapa kotak hari
          tampak lebih bersih daripada kenyataannya. */}
      {data?.legacy_jobs_without_closed_at > 0 && data?.legacy_note && (
        <div className="flex items-start gap-2 border-b border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.1)] px-4 py-2.5"
          data-testid="cmt-week-legacy-jobs">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-[hsl(var(--warning-text))]" />
          <p className="text-xs leading-snug text-[hsl(var(--warning-text))]">
            <span className="font-semibold">Sebagian kotak hari belum bisa dihitung penuh — </span>
            {data.legacy_note}
          </p>
        </div>
      )}

      {/* ── Catatan rentang & aturan ─────────────────────────────────────── */}
      {data?.as_of_note && (
        <div className="flex items-start gap-2 border-b border-border bg-muted/40 px-4 py-2.5"
          data-testid="cmt-week-as-of-note">
          <Info className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-[hsl(var(--primary))]" />
          <p className="text-xs leading-snug text-muted-foreground">{data.as_of_note}</p>
        </div>
      )}

      {/* ── Tabel ────────────────────────────────────────────────────────── */}
      {err ? (
        <div className="p-4">
          <Notice tone="danger" icon={XCircle} testId="cmt-week-error">{err}</Notice>
        </div>
      ) : loading ? (
        <div className="flex items-center justify-center py-8" data-testid="cmt-week-loading">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : visible.length === 0 ? (
        <EmptyState
          testId="cmt-week-empty"
          icon={CheckCircle2}
          title={rows.length === 0
            ? 'Belum ada vendor CMT aktif di master'
            : onlyWorse
              ? 'Tidak ada vendor yang memburuk dibanding pekan lalu'
              : onlyProblem
                ? 'Tidak ada vendor bermasalah dalam 7 hari ini — semua rapi'
                : 'Tidak ada vendor yang cocok dengan pencarian'}
          description={rows.length === 0
            ? 'Aktifkan vendor CMT di master vendor supaya muncul di rekap ini.'
            : 'Ubah pencarian atau penyaring untuk melihat vendor lain.'}
          action={(onlyWorse || onlyProblem) && rows.length > 0 ? (
            <Button type="button" variant="outline" size="sm"
              onClick={() => { setOnlyWorse(false); setOnlyProblem(false); }}
              data-testid="cmt-week-clear-filters">
              <X className="mr-1.5 h-3.5 w-3.5" /> Tampilkan semua vendor
            </Button>
          ) : null}
        />
      ) : (
        <ResponsiveTableWrapper stickyFirstCol>
          <table className={`w-full text-sm ${showCompareCol ? 'min-w-[1500px]' : 'min-w-[1320px]'}`}>
            <thead className="bg-muted/60">
              <tr className="text-left text-xs text-muted-foreground">
                <th className="px-4 py-2.5">Vendor</th>
                {days.map(d => {
                  const pd = perDayMap[d.date] || {};
                  const npend = Number(pd.vendors_pending || 0);
                  return (
                    <th key={d.date} className="px-1 py-2 text-center font-semibold">
                      <Button type="button" variant="ghost" onClick={() => openDay(d.date)}
                        disabled={d.is_future}
                        className="h-auto w-full flex-col gap-0 rounded-md px-1 py-0.5 font-normal leading-tight"
                        title={d.is_future
                          ? `${d.date} — belum terjadi`
                          : `${d.date} — buka Rekap Harian tanggal ini`}
                        data-testid={`cmt-week-dayhead-${d.date}`}>
                        <span className={`block text-xs ${d.is_today ? 'text-[hsl(var(--primary))]' : ''}`}>
                          {d.short}
                        </span>
                        <span className="block text-xs font-bold text-foreground">
                          {d.day_num}
                        </span>
                        {d.is_future ? (
                          <span className="mt-0.5 block text-xs font-normal normal-case">—</span>
                        ) : (
                          <span className={`mt-0.5 block rounded-full px-1 text-xs font-bold normal-case ${
                            npend > 0 ? 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--danger-text))]' : 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success-text))]'
                          }`} data-testid={`cmt-week-daycount-${d.date}`}>
                            {npend > 0 ? `${npend} belum` : 'aman'}
                          </span>
                        )}
                      </Button>
                    </th>
                  );
                })}
                <th className="px-2 py-2.5 text-center">Terlambat</th>
                <th className="px-2 py-2.5 text-center">Belum beres</th>
                <th className="px-2 py-2.5 text-center">Tanpa setoran</th>
                <th className="px-2 py-2.5 text-center">Pcs setor / kirim</th>
                {showCompareCol && (
                  <th className="px-2 py-2.5 text-center" data-testid="cmt-week-th-vs-prev">
                    vs pekan lalu
                  </th>
                )}
                <th className="px-2 py-2.5 text-center">Tren pcs</th>
                <th className="px-2 py-2.5 text-center">Streak</th>
                <th className="px-3 py-2.5 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {visible.map(r => {
                const stat = ROW_STATUS[r.status] || ROW_STATUS.idle;
                return (
                  <tr key={r.vendor_id} className="align-middle hover:bg-muted/30"
                    data-testid={`cmt-week-row-${r.vendor_id}`} data-status={r.status}>
                    <td className="px-4 py-3">
                      <p className="font-semibold text-foreground">{r.vendor_name}</p>
                      <p className="mt-0.5 tabular-nums text-xs text-muted-foreground">
                        {r.vendor_code || '—'}
                      </p>
                      <span className={`mt-1.5 inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-bold ${stat.cls}`}
                        data-testid={`cmt-week-status-${r.vendor_id}`}>
                        {stat.text}
                      </span>
                      {r.has_active_portal_account && (
                        <span className="mt-1 flex items-center gap-1 text-xs text-[hsl(var(--warning-text))]"
                          title="Vendor ini punya akun portal aktif — hati-hati dobel input">
                          <AlertTriangle className="h-3 w-3" /> punya akun portal
                        </span>
                      )}
                    </td>

                    {(r.cells || []).map(c => (
                      <td key={c.date} className="px-1 py-3">
                        <DayBox cell={c} vendorId={r.vendor_id} onOpen={openDay} />
                      </td>
                    ))}

                    <td className="px-2 py-3 text-center" data-testid={`cmt-week-late-${r.vendor_id}`}>
                      <span className={`inline-flex min-w-[2rem] justify-center rounded-md px-2 py-1 text-sm font-bold ${
                        r.days_late > 0 ? 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--danger-text))]' : 'text-muted-foreground'
                      }`}>
                        {r.days_late}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">hari</span>
                    </td>
                    <td className="px-2 py-3 text-center" data-testid={`cmt-week-unfinished-${r.vendor_id}`}>
                      <span className={`inline-flex min-w-[2rem] justify-center rounded-md px-2 py-1 text-sm font-bold ${
                        r.days_unfinished > 0 ? 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning-text))]' : 'text-muted-foreground'
                      }`}>
                        {r.days_unfinished}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">hari</span>
                    </td>
                    <td className="px-2 py-3 text-center" data-testid={`cmt-week-nosetor-${r.vendor_id}`}>
                      <span className={`text-sm font-bold ${
                        r.days_no_progress > 0 ? 'text-foreground' : 'text-muted-foreground'
                      }`}>
                        {r.days_no_progress}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        dari {r.days_with_work} hari kerja
                      </span>
                    </td>
                    <td className="px-2 py-3 text-center" data-testid={`cmt-week-qty-${r.vendor_id}`}>
                      <p className="text-sm font-bold text-foreground">{r.qty_progress_total}</p>
                      <p className="text-xs text-muted-foreground">
                        kirim {r.qty_shipped_total}
                      </p>
                    </td>
                    {showCompareCol && (() => {
                      const cv = cmpByVendor[r.vendor_id];
                      if (!cv) {
                        return (
                          <td className="px-2 py-3 text-center text-xs text-muted-foreground"
                            data-testid={`cmt-week-vs-${r.vendor_id}`} data-direction="unknown">—</td>
                        );
                      }
                      // Vendor yang tidak bisa dibandingkan TIDAK dikosongkan
                      // begitu saja: alasannya ditulis, supaya tidak terbaca
                      // sebagai "tidak ada perubahan".
                      if (cv.direction === 'incomparable') {
                        return (
                          <td className="px-2 py-3 text-center"
                            data-testid={`cmt-week-vs-${r.vendor_id}`} data-direction="incomparable"
                            title={cv.incomparable_reason}>
                            <span className="inline-block rounded-full bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground">
                              tak sebanding
                            </span>
                            <p className="mt-1 max-w-[9rem] text-xs leading-tight text-muted-foreground">
                              {cv.incomparable_reason}
                            </p>
                          </td>
                        );
                      }
                      return (
                        <td className="px-2 py-3 text-center"
                          data-testid={`cmt-week-vs-${r.vendor_id}`} data-direction={cv.direction}>
                          <p className="flex justify-center">
                            <DeltaNum diff={cv.days_late_diff} lowerIsBetter unit=" hari"
                              testid={`cmt-week-vs-late-${r.vendor_id}`} />
                          </p>
                          <p className="mt-0.5 flex justify-center">
                            <DeltaNum diff={cv.qty_diff} unit=" pcs"
                              testid={`cmt-week-vs-qty-${r.vendor_id}`} />
                          </p>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            lalu: {cv.days_late_prev} hari · {cv.qty_prev} pcs
                          </p>
                        </td>
                      );
                    })()}
                    <td className="px-2 py-3">
                      <div className="flex justify-center">
                        <Sparkline values={r.trend} testid={`cmt-week-spark-${r.vendor_id}`}
                          title={`Pcs disetor per hari: ${(r.trend || []).join(', ')}`} />
                      </div>
                    </td>
                    <td className="px-2 py-3 text-center" data-testid={`cmt-week-streak-${r.vendor_id}`}>
                      <span className="inline-flex items-center gap-1 text-sm font-bold text-foreground">
                        {r.streak > 0 && <Flame className="h-3.5 w-3.5 text-[hsl(var(--warning-text))]" />}
                        {r.streak}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {r.streak_broken_by === 'pending'
                          ? 'putus: hari terlambat'
                          : r.streak_broken_by === 'partial'
                            ? 'putus: masih ada sisa'
                            : r.streak > 0 ? 'hari beruntun' : 'belum ada'}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right">
                      <Button type="button" size="sm" variant="outline" className="whitespace-nowrap"
                        onClick={() => openVendor(r)} disabled={!canFill}
                        data-testid={`cmt-week-fill-${r.vendor_id}`}>
                        <UserCog className="mr-1.5 h-3.5 w-3.5" /> Isi
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </ResponsiveTableWrapper>
      )}

      {/* ── Legenda + aturan ────────────────────────────────────────────── */}
      <div className="space-y-2 border-t border-border px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">Keterangan:</span>
          <span className="inline-flex items-center gap-1"><XCircle className="h-3.5 w-3.5 text-[hsl(var(--danger-text))]" /> terlambat (ada pekerjaan, nol bukti)</span>
          <span className="inline-flex items-center gap-1"><AlertTriangle className="h-3.5 w-3.5 text-[hsl(var(--warning-text))]" /> terisi, masih ada sisa</span>
          <span className="inline-flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5 text-[hsl(var(--success-text))]" /> lengkap</span>
          <span className="inline-flex items-center gap-1"><MinusCircle className="h-3.5 w-3.5" /> tidak ada pekerjaan</span>
          <span className="inline-flex items-center gap-1"><TrendingUp className="h-3 w-3" /> batang = pcs disetor hari itu</span>
          {compare && (
            <span className="inline-flex items-center gap-1" data-testid="cmt-week-legend-compare">
              <GitCompareArrows className="h-3 w-3" /> hijau = membaik · merah = memburuk
              (dibanding pekan sebelumnya)
            </span>
          )}
          <span className="ml-auto inline-flex items-center gap-1"><Download className="h-3 w-3" />
            Excel/PDF isinya sama dengan layar ini{compare ? ' (termasuk perbandingan)' : ''}
          </span>
        </div>
        {data?.rules_note && (
          <p className="text-xs leading-snug text-muted-foreground" data-testid="cmt-week-rules-note">
            {data.rules_note}
          </p>
        )}
      </div>
    </GlassCard>
  );
}

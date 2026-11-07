/**
 * CMTOverrideDailyRecap — **Rekap Harian** di dalam pintu "Input Vendor CMT".
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * MASALAH NYATA
 * ═══════════════════════════════════════════════════════════════════════════
 * Staf DA sudah bisa mengisi portal vendor CMT atas nama vendor, tapi tidak ada
 * yang memberitahu **vendor mana yang belum dikerjakan hari ini**. Dengan puluhan
 * vendor, satu yang terlewat = progress hari itu tidak masuk, dan karena
 * **tagihan CMT dihitung dari progress produksi**, uangnya tidak bisa ditagih.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * KEPUTUSAN OWNER (2026-08-08)
 * ═══════════════════════════════════════════════════════════════════════════
 *  1c  Bentuknya **checklist per tugas** (bukan lampu hijau/merah tunggal) —
 *      satu baris per vendor, kolom per jenis pekerjaan, supaya kelihatan
 *      KURANG APA, bukan cuma "belum beres".
 *  2a  Isinya **SEMUA vendor aktif**; yang tidak punya pekerjaan tetap tampil
 *      dengan status "tidak ada pekerjaan" (jangan menghilangkan nama tanpa
 *      penjelasan — staf akan curiga daftarnya tidak lengkap).
 *  3a  Yang **diisi vendor sendiri** ikut dihitung ✓, dengan tanda sumbernya.
 *  4a  Rekap = **blok pertama** layar, di atas kartu pilih vendor.
 *  5   Tambahan: lihat tanggal lain · export Excel/PDF · kirim reminder.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * KENAPA CHIP-NYA BISA DIKLIK
 * ═══════════════════════════════════════════════════════════════════════════
 * Rekap yang cuma bisa dibaca akan memaksa staf mengingat "tadi yang merah siapa,
 * kolomnya apa" lalu mencari kartunya di bawah dan menebak tabnya. Setiap chip ✗
 * membawa `module` dari backend, jadi satu klik = langsung masuk mode override
 * vendor itu DENGAN tab yang tepat sudah terbuka.
 *
 * Angka di sini TIDAK dihitung ulang di browser — semuanya datang dari
 * `GET /api/cmt-override/daily-recap` (SSOT `backend/core/cmt_daily_recap.py`),
 * yang juga dipakai berkas export dan tombol reminder. Kalau frontend ikut
 * menghitung, suatu hari kartu ringkasan akan berdebat dengan tabelnya sendiri.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, BellRing, CalendarDays, CheckCircle2, ChevronLeft, ChevronRight,
  Download, FileSpreadsheet, FileText, Info, Loader2, MinusCircle,
  RefreshCw, Search, UserCog, X, XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import DatePicker from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Toolbar } from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { apiGet, apiPost, apiFetch } from '../../../lib/api';
import { dayLabel, isoToday, shiftDay } from './recapDates';

// ── Tampilan per status kolom (empat status, bukan dua — lihat SSOT backend) ──
// Standar UI/UX v2 (8 Nov 2026): sel tanpa kotak berwarna tebal (dulu tiap sel kotak bergaris → baris setinggi
// 120 px); warna hanya pada ikon & teks status.
const CELL_STYLE = {
  done: { Icon: CheckCircle2, cls: 'text-[hsl(var(--success-text))]', label: 'Sudah diisi' },
  partial: { Icon: AlertTriangle, cls: 'text-[hsl(var(--warning-text))]', label: 'Sudah diisi, masih ada sisa' },
  pending: { Icon: XCircle, cls: 'text-[hsl(var(--danger-text))]', label: 'Belum diisi' },
  none: { Icon: MinusCircle, cls: 'text-muted-foreground', label: 'Tidak ada pekerjaan' },
};

const ROW_STATUS = {
  pending: { text: 'Belum diisi', tone: 'danger' },
  partial: { text: 'Sebagian', tone: 'warning' },
  done: { text: 'Lengkap', tone: 'success' },
  idle: { text: 'Tidak ada pekerjaan', tone: 'muted' },
};

const SOURCE_TEXT = { staff: 'staf DA', vendor: 'vendor', mixed: 'staf + vendor' };

// `isoToday` / `shiftDay` / `dayLabel` pindah ke `./recapDates` (fase 4): tab
// Mingguan dan panel induknya memakai helper yang SAMA. Salinan per-komponen
// adalah salinan yang suatu hari akan berbeda — dan dua tab yang tidak setuju
// tentang "hari ini" adalah bug yang sangat mahal dilacak.

// ═════════════════════════════════════════════════════════════════════════════
// PANDUAN_UI G5: kartu angka = StatTile netral; warna hanya pada angkanya.
const STAT_ACCENT = { red: 'danger', amber: 'warning', green: 'success', grey: 'muted', blue: 'primary' };
function StatCard({ testid, label, value, tone, hint }) {
  return <StatTile testId={testid} label={label} value={value} sub={hint || undefined} accent={STAT_ACCENT[tone] || 'muted'} />;
}

// ═════════════════════════════════════════════════════════════════════════════
function TaskCell({ row, taskKey, task, onOpen, canFill }) {
  const vendorId = row.vendor_id;
  const st = CELL_STYLE[task?.state] || CELL_STYLE.none;
  const { Icon } = st;
  const src = SOURCE_TEXT[task?.source] || '';
  const clickable = canFill && task?.state !== 'none';
  // Untuk sel "—", keterangan backend-nya memang sama dengan labelnya ⇒ jangan
  // dicetak dua kali (tabel 5 kolom cepat penuh kebisingan dan yang merah jadi
  // sulit ditemukan — padahal justru itu yang dicari staf).
  const detail = (task?.detail && task.detail !== st.label) ? task.detail : '';
  const body = (
    <span className={`block min-w-0 ${st.cls}`}>
      <span className="flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5 flex-shrink-0" />
        <span className="text-xs font-medium">{st.label}</span>
      </span>
      {detail ? <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">{detail}</span> : null}
      {src ? <span className="mt-0.5 block text-xs text-muted-foreground">diisi {src}</span> : null}
    </span>
  );

  if (!clickable) {
    return (
      <div className="px-2 py-1" data-testid={`cmt-recap-cell-${vendorId}-${taskKey}`} data-state={task?.state || 'none'}>
        {body}
      </div>
    );
  }
  return (
    <Button type="button" variant="ghost" onClick={() => onOpen(row, task?.module)} title={`Buka modul ini untuk ${taskKey}`}
      className="h-auto w-full justify-start whitespace-normal px-2 py-1 text-left font-normal"
      data-testid={`cmt-recap-cell-${vendorId}-${taskKey}`} data-state={task?.state || 'none'}>
      {body}
    </Button>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
/**
 * Props tanggal (fase 4 — Rekap Mingguan):
 *   `day` + `onDayChange` membuat komponen ini **terkendali** oleh
 *   `CMTOverrideRecapPanel`, supaya klik satu kotak hari di tab Mingguan bisa
 *   membuka tab Harian PADA TANGGAL ITU. Tanpa prop, komponen tetap memegang
 *   tanggalnya sendiri (dipakai bila dirender langsung tanpa panel).
 */
export default function CMTOverrideDailyRecap({
  onOpenVendor, canFill = true, day: dayProp, onDayChange, viewSwitch = null,
}) {
  const [dayLocal, setDayLocal] = useState(isoToday);
  const controlled = typeof dayProp === 'string' && !!dayProp;
  const day = controlled ? dayProp : dayLocal;

  const setDay = useCallback((next) => {
    const val = typeof next === 'function' ? next(day) : next;
    if (typeof onDayChange === 'function') onDayChange(val);
    if (!controlled) setDayLocal(val);
  }, [controlled, day, onDayChange]);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [onlyPending, setOnlyPending] = useState(false);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState('');
  const [confirmRemind, setConfirmRemind] = useState(false);   // dipertahankan: sendReminders menutupnya

  const load = useCallback(async (d) => {
    setLoading(true); setErr('');
    try {
      const res = await apiGet(`/cmt-override/daily-recap?date=${d}`);
      setData(res);
    } catch (e) {
      setErr(e.message || 'Gagal memuat rekap harian');
      setData(null);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(day); }, [day, load]);

  const tasks = data?.tasks || [];
  const summary = data?.summary || {};
  // `useMemo` supaya identitas array-nya stabil: tanpa ini, dua useMemo turunan
  // di bawah dihitung ulang setiap render (dan ESLint memperingatkannya).
  const rows = useMemo(() => data?.rows || [], [data]);
  const isToday = day === isoToday();

  const pendingRows = useMemo(() => rows.filter(r => r.status === 'pending'), [rows]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter(r => {
      if (onlyPending && r.status !== 'pending' && r.status !== 'partial') return false;
      if (!q) return true;
      return `${r.vendor_name} ${r.vendor_code} ${r.contact_name}`.toLowerCase().includes(q);
    });
  }, [rows, onlyPending, search]);

  const download = async (fmt) => {
    setBusy(fmt);
    try {
      const res = await apiFetch(`/cmt-override/daily-recap/export?format=${fmt}&date=${day}`);
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
      a.download = guess || `rekap-harian-cmt-${day}.${fmt}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(`Rekap ${fmt.toUpperCase()} tanggal ${day} diunduh.`);
    } catch (e) {
      toast.error(e.message || 'Gagal mengunduh rekap');
    } finally { setBusy(''); }
  };

  const sendReminders = async () => {
    setBusy('remind');
    try {
      const res = await apiPost('/cmt-override/daily-recap/remind', { date: day });
      const sent = res?.sent_count || 0;
      const skipped = res?.skipped_count || 0;
      if (sent > 0) {
        toast.success(
          `Reminder terkirim ke ${sent} vendor.` +
          (skipped ? ` ${skipped} dilewati (sudah ditegur untuk tanggal ini).` : ''),
        );
      } else if (skipped > 0) {
        toast.info(`Tidak ada yang dikirim — ${skipped} vendor sudah ditegur untuk tanggal ini.`);
      } else {
        toast.info('Tidak ada vendor yang perlu ditegur.');
      }
      setConfirmRemind(false);
      load(day);
    } catch (e) {
      toast.error(e.message || 'Gagal mengirim reminder');
    } finally { setBusy(''); }
  };

  // Baris rekap dikirim UTUH ke induk (bukan cuma id): induk butuh nama +
  // status akun portal untuk spanduk & peringatan dobel input, dan tidak boleh
  // bergantung pada daftar vendor yang mungkin belum selesai dimuat.
  const openVendor = (row, moduleId) => {
    if (typeof onOpenVendor === 'function') onOpenVendor(row, moduleId);
  };

  // Konfirmasi reminder lewat dialog aplikasi — staf tetap MELIHAT siapa yang akan ditegur (daftar di badan dialog).
  const askRemind = async () => {
    const daftar = pendingRows.map((r) => `• ${r.vendor_name} — ${(r.pending_tasks || []).join(', ')}`).join('\n');
    const ok = await confirmDialog({
      title: `Kirim reminder ke ${pendingRows.length} vendor yang belum diisi?`,
      body: `Reminder masuk ke Pengingat vendor; satu vendor hanya menerima satu reminder rekap per tanggal.\n\n${daftar}`,
      confirmLabel: 'Ya, kirim sekarang',
    });
    if (ok) sendReminders();
  };

  return (
    <div className="space-y-4" data-testid="cmt-recap-panel">
      <Toolbar testId="cmt-recap-day-toolbar"
        filters={<>
          {viewSwitch}
          <div className="flex items-center gap-1">
            <Button variant="outline" size="icon" onClick={() => setDay(d => shiftDay(d, -1))}
              title="Hari sebelumnya" aria-label="Hari sebelumnya" data-testid="cmt-recap-prev-day">
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <div className="w-44">
              <DatePicker value={day} max={shiftDay(isoToday(), 1)} bolehKosong={false}
                onChange={(v) => v && setDay(v)} testId="cmt-recap-date-input" />
            </div>
            <Button variant="outline" size="icon" onClick={() => setDay(d => shiftDay(d, 1))}
              title="Hari berikutnya" aria-label="Hari berikutnya" data-testid="cmt-recap-next-day">
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
          {isToday ? <StatusBadge status="today" tone="primary" label="Hari ini" testId="cmt-recap-day-label" />
            : <Button variant="link" size="sm" onClick={() => setDay(isoToday())} data-testid="cmt-recap-today">Kembali ke hari ini</Button>}
        </>}
        tools={<>
          <Button variant="outline" size="icon" onClick={() => load(day)}
            title="Muat ulang" aria-label="Muat ulang" data-testid="cmt-recap-refresh">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
          <Button variant="outline" onClick={() => download('xlsx')} disabled={busy === 'xlsx'} data-testid="cmt-recap-export-xlsx"
            title="Unduh Excel (isinya sama dengan layar ini)">
            {busy === 'xlsx' ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSpreadsheet className="h-4 w-4" />}
            Excel
          </Button>
          <Button variant="outline" onClick={() => download('pdf')} disabled={busy === 'pdf'} data-testid="cmt-recap-export-pdf"
            title="Unduh PDF (isinya sama dengan layar ini)">
            {busy === 'pdf' ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
            PDF
          </Button>
        </>} />

      {/* Ringkasan — satu kalimat (dulu 5 kartu tinggi yang mendorong tabel ke bawah). Angka dari server (`summary`),
          dihitung atas SEMUA vendor aktif untuk tanggal ini. */}
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm" data-testid="cmt-recap-summary">
        <span><b className={`tabular-nums ${summary.vendors_pending ? 'text-[hsl(var(--danger-text))]' : ''}`} data-testid="cmt-recap-summary-pending">{summary.vendors_pending ?? '—'}</b> vendor belum diisi
          (<span className="tabular-nums" data-testid="cmt-recap-summary-tasks">{summary.tasks_pending_total ?? 0}</span> tugas)</span>
        <span><b className={`tabular-nums ${summary.vendors_partial ? 'text-[hsl(var(--warning-text))]' : ''}`} data-testid="cmt-recap-summary-partial">{summary.vendors_partial ?? '—'}</b> sebagian</span>
        <span><b className="tabular-nums" data-testid="cmt-recap-summary-done">{summary.vendors_done ?? '—'}</b> lengkap</span>
        <span><b className="tabular-nums" data-testid="cmt-recap-summary-idle">{summary.vendors_idle ?? '—'}</b> tanpa pekerjaan</span>
        <span className="text-muted-foreground"><span className="tabular-nums">{summary.qty_progress_today ?? 0}</span> pcs progress masuk</span>
      </p>

      <Toolbar testId="cmt-recap-filter-toolbar"
        filters={<>
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari vendor" className="pl-8" data-testid="cmt-recap-search" />
          </div>
          <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-foreground">
            <Checkbox checked={onlyPending} onCheckedChange={(v) => setOnlyPending(!!v)} data-testid="cmt-recap-filter-pending" />
            Hanya yang belum lengkap
          </label>
        </>}
        tools={<Button variant="outline" onClick={askRemind} disabled={pendingRows.length === 0 || busy === 'remind'} data-testid="cmt-recap-remind">
          {busy === 'remind' ? <Loader2 className="h-4 w-4 animate-spin" /> : <BellRing className="h-4 w-4" />}
          Kirim reminder ({pendingRows.length})
        </Button>} />

      {/* Job WARISAN tanpa stempel waktu tutup (fase 5 `closed_at`) — batas kemampuan rekap untuk tanggal lampau. */}
      {data?.legacy_jobs_without_closed_at > 0 && data?.legacy_note && (
        <Notice tone="warning" icon={AlertTriangle} testId="cmt-recap-legacy-jobs" title="Sebagian tanggal lampau belum bisa dihitung penuh">
          {data.legacy_note}
        </Notice>
      )}
      {/* Catatan kejujuran data untuk tanggal lampau */}
      {!isToday && (data?.as_of_note_base || data?.as_of_note) && (
        <Notice tone="info" icon={Info} testId="cmt-recap-as-of-note">{data.as_of_note_base || data.as_of_note}</Notice>
      )}

      {err ? (
        <Notice tone="danger" icon={XCircle} testId="cmt-recap-error">{err}</Notice>
      ) : loading ? (
        <div className="flex items-center justify-center py-8" data-testid="cmt-recap-loading">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : visible.length === 0 ? (
        <EmptyState icon={CheckCircle2} testId="cmt-recap-empty"
          title={rows.length === 0
            ? 'Belum ada vendor CMT aktif di master'
            : onlyPending
              ? 'Tidak ada vendor yang belum lengkap — semua sudah diisi'
              : 'Tidak ada vendor yang cocok dengan pencarian'}
          description={rows.length === 0
            ? 'Aktifkan vendor CMT di Master Data supaya muncul di rekap.'
            : onlyPending
              ? 'Matikan "Hanya yang belum lengkap" untuk melihat semua vendor.'
              : 'Ubah kata pencarian atau kosongkan kotak cari.'} />
      ) : (
        <div className="overflow-x-auto">
          <Table className="min-w-[56rem]">
            <TableHeader><TableRow>
              <TableHead>Vendor</TableHead>
              {tasks.map(t => <TableHead key={t.key}>{t.label}</TableHead>)}
              <TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {visible.map(r => {
                const stat = ROW_STATUS[r.status] || ROW_STATUS.idle;
                return (
                  <TableRow key={r.vendor_id} className="align-top" data-testid={`cmt-recap-row-${r.vendor_id}`} data-status={r.status}>
                    <TableCell>
                      <p className="font-medium text-foreground">{r.vendor_name}</p>
                      <p className="text-xs text-muted-foreground tabular-nums">{r.vendor_code || '—'}</p>
                      <span className="mt-1 inline-flex" data-testid={`cmt-recap-status-${r.vendor_id}`}>
                        <StatusBadge status={r.status} label={stat.text} tone={stat.tone} />
                      </span>
                      {r.has_active_portal_account && (
                        <span className="mt-1 flex items-center gap-1 text-xs text-[hsl(var(--warning-text))]"
                          title="Vendor ini punya akun portal aktif — hati-hati dobel input">
                          <AlertTriangle className="h-3 w-3" /> punya akun portal
                        </span>
                      )}
                    </TableCell>
                    {tasks.map(t => (
                      <TableCell key={t.key} className="px-1">
                        <TaskCell row={r} taskKey={t.key} task={(r.tasks || {})[t.key]} onOpen={openVendor} canFill={canFill} />
                      </TableCell>
                    ))}
                    <TableCell className="text-right">
                      <Button size="sm" variant="outline" className="whitespace-nowrap" onClick={() => openVendor(r, null)}
                        data-testid={`cmt-recap-fill-${r.vendor_id}`}>
                        <UserCog className="h-3.5 w-3.5" /> Isi
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Keterangan (klik "Belum diisi" untuk membuka modulnya atas nama vendor):</span>
        <span className="inline-flex items-center gap-1"><XCircle className="h-3.5 w-3.5 text-[hsl(var(--danger-text))]" /> belum diisi (ada pekerjaan menunggu)</span>
        <span className="inline-flex items-center gap-1"><AlertTriangle className="h-3.5 w-3.5 text-[hsl(var(--warning-text))]" /> sudah diisi, masih ada sisa</span>
        <span className="inline-flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5 text-[hsl(var(--success-text))]" /> sudah diisi</span>
        <span className="inline-flex items-center gap-1"><MinusCircle className="h-3.5 w-3.5" /> tidak ada pekerjaan</span>
        <span className="inline-flex items-center gap-1"><Download className="h-3 w-3" /> Excel/PDF isinya sama dengan layar ini</span>
      </p>
    </div>
  );
}

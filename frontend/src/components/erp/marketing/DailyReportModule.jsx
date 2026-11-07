/**
 * DailyReportModule — Laporan Harian PIC Portal Marketing (F10, sesi #10)
 *
 * KENAPA LAYAR INI DIUBAH
 * -----------------------
 * Sebelumnya layar ini satu-satunya pintu Portal Marketing yang menampilkan
 * DAFTAR (9 toko × status input harian) sebagai **tumpukan baris kartu**: tidak
 * bisa diurutkan, tidak bisa dicari, tidak bisa diunduh, dan — yang paling mahal —
 * **menyembunyikan satu field yang dikirim backend**: `sales_status.entered_live`.
 * Akibatnya toko yang sudah mengisi omzet TOTAL tetapi belum mengisi omzet LIVE
 * tampak "sudah beres" (centang hijau), padahal justru angka live-lah yang dipakai
 * menilai sesi live host. Pertanyaan harian SPV ("siapa yang belum input hari
 * ini?") hanya bisa dijawab dengan menggulir dan menghitung sendiri.
 *
 * Sekarang: **tabel nyata** (7 kolom, bisa diurutkan tiap kolom), pencarian,
 * pengalih Tabel/Kartu, unduh CSV, dan kolom "Live" yang memisahkan dua jenis
 * input. Tombol **Eksekusi** (input sales cepat) dipertahankan persis.
 *
 * YANG WAJIB TETAP ADA (jangan dihapus saat merapikan tampilan):
 *  · pembeda input TOTAL vs LIVE — dua pertanyaan berbeda, dua kolom berbeda;
 *  · keadaan kosong yang MENJELASKAN diri (staf tanpa toko ⇒ panel
 *    `NoStoreScopeNotice`, bukan tabel kosong tanpa sebab);
 *  · tombol Eksekusi hanya muncul bila memang ada task input sales yang pending.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, DatePicker (dulu input tanggal bawaan), 6 kartu → 4 StatTile,
 * tabel standar (kolom tetap bisa diurutkan) + unduh Excel/CSV, popup Eksekusi = FormPopup, warna token.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  CalendarCheck, RefreshCw, CheckCircle2, XCircle, AlertTriangle,
  ChevronLeft, ChevronRight, Zap, Search, ArrowUpDown,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import ViewToggle from '@/components/ui/view-toggle';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';
import NoStoreScopeNotice from './NoStoreScopeNotice';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';
import { daysAgoWIB, addDaysISO } from '@/lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL;
const fmtRp = formatRupiah;
const fmtNum = (n) => new Intl.NumberFormat('id-ID').format(n || 0);
const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok', tiktokshop: 'TikTok', tokopedia: 'Tokopedia', lazada: 'Lazada' };
const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '—';
const PRIORITAS = { high: { label: 'Tinggi', tone: 'danger' }, medium: { label: 'Sedang', tone: 'warning' }, low: { label: 'Rendah', tone: 'muted' } };
const JENIS_AKSI = { submit_form: 'Isi formulir', input_sales: 'Input sales', upload_file: 'Unggah berkas', approve: 'Persetujuan', review: 'Tinjau' };

// ─── Quick Sales Dialog ────────────────────────────────────────────────────────
function QuickSalesDialog({ open, onClose, account, task, date, token, onSuccess }) {
  const [form, setForm] = useState({ revenue: '', orders: '' });
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');

  const handleSubmit = async () => {
    const revenue = parseFloat(form.revenue);
    const orders  = parseInt(form.orders, 10);
    if (!revenue || revenue <= 0) { setGalat('Omzet wajib diisi.'); return; }
    setGalat('');
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/marketing/tasks/${task.id}/complete-action`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action_data: { revenue, orders: orders || 0, date },
          completion_notes: `Input via Laporan Harian — ${date}`,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Gagal eksekusi');
      toast.success(`Sales ${account.account_name} berhasil diinput`);
      onSuccess();
      onClose();
    } catch (e) { setGalat(e.message); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" onSimpan={handleSubmit} menyimpan={saving} galat={galat}
      judul="Input sales cepat" keterangan={`${account?.account_name || ''} · ${formatTanggalID(date)}`}
      labelSimpan="Simpan & selesaikan tugas" testId="quick-sales-dialog">
      <Isian label="Omzet (Rp)" wajib>
        <MoneyInput value={form.revenue}
          onChange={(e) => setForm((f) => ({ ...f, revenue: e.target.value }))}
          placeholder="Contoh: 4.500.000" data-testid="quick-revenue-input" autoFocus />
      </Isian>
      <Isian label="Jumlah pesanan" htmlFor="quick-orders">
        <Input id="quick-orders" type="number" min={0} value={form.orders}
          onChange={(e) => setForm((f) => ({ ...f, orders: e.target.value }))}
          placeholder="Contoh: 42" data-testid="quick-orders-input" />
      </Isian>
    </FormPopup>
  );
}

function YesNo({ ok, yes = 'Sudah', no = 'Belum' }) {
  return ok ? (
    <span className="inline-flex items-center gap-1 text-[hsl(var(--success-text))]">
      <CheckCircle2 size={14} /> {yes}
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-[hsl(var(--danger-text))]">
      <XCircle size={14} /> {no}
    </span>
  );
}

/* Kolom tabel = kontrak layar ini. `get` dipakai untuk mengurutkan DAN menyusun
   CSV, jadi angka di berkas unduhan tidak mungkin berbeda dari yang di layar. */
const COLUMNS = [
  { key: 'account', label: 'Toko', get: (a) => (a.account_name || '').toLowerCase() },
  { key: 'total', label: 'Input harian', get: (a) => (a.sales_status?.entered_total ? 1 : 0) },
  { key: 'revenue', label: 'Omzet diinput', get: (a) => Number(a.sales_status?.revenue || 0), num: true },
  { key: 'orders', label: 'Pesanan', get: (a) => Number(a.sales_status?.orders || 0), num: true },
  { key: 'live', label: 'Input live', get: (a) => (a.sales_status?.entered_live ? 1 : 0) },
  { key: 'health', label: 'Skor kesehatan', get: (a) => (a.health_score == null ? -1 : Number(a.health_score)), num: true },
  { key: 'tasks', label: 'Tugas menunggu', get: (a) => (a.pending_action_tasks || []).length, num: true },
  { key: 'overdue', label: 'Terlambat', get: (a) => Number(a.overdue_count || 0), num: true },
];

export default function DailyReportModule({ token }) {
  // Bawaan = KEMARIN menurut kalender WIB (bukan tanggal UTC/perangkat).
  const [date, setDate]       = useState(() => daysAgoWIB(1));
  const [report, setReport]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [eksekusiTarget, setEksekusiTarget] = useState(null); // { account, task }

  // F10 — daftar yang bisa DIPAKAI: cari, urutkan, unduh, dan dua tipe tampilan.
  const [q, setQ] = useState('');
  const [sortKey, setSortKey] = useState('account');
  const [sortDir, setSortDir] = useState(1);
  const [view, setView] = useState('table');   // 'table' | 'cards'
  const [onlyMissing, setOnlyMissing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/marketing/reports/daily?date=${date}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`Gagal memuat laporan (HTTP ${res.status})`);
      setReport(await res.json());
    } catch (e) { toast.error(e.message); setReport(null); }
    finally { setLoading(false); }
  }, [date, token]);

  useEffect(() => { load(); }, [load]);

  const prevDay = () => setDate(addDaysISO(date, -1));
  const nextDay = () => setDate(addDaysISO(date, 1));

  const s = report?.summary || {};
  const accounts = report?.accounts || [];
  const criticals = accounts.filter((a) => a.health_score != null && a.health_score < 60);
  const allPendingTasks = accounts.flatMap((a) =>
    (a.pending_action_tasks || []).map((t) => ({ ...t, _account: a })));

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let out = accounts.filter((a) => {
      if (onlyMissing && a.sales_status?.entered_total) return false;
      if (!needle) return true;
      return [a.account_name, a.account_code, a.platform]
        .some((v) => String(v || '').toLowerCase().includes(needle));
    });
    const col = COLUMNS.find((c) => c.key === sortKey) || COLUMNS[0];
    out = [...out].sort((x, y) => {
      const a = col.get(x); const b = col.get(y);
      if (a === b) return (x.account_name || '').localeCompare(y.account_name || '');
      return (a > b ? 1 : -1) * sortDir;
    });
    return out;
  }, [accounts, q, onlyMissing, sortKey, sortDir]);

  const toggleSort = (key) => {
    if (key === sortKey) setSortDir((d) => -d);
    else { setSortKey(key); setSortDir(key === 'account' ? 1 : -1); }
  };

  const salesTaskOf = (acc) => (acc.pending_action_tasks || []).find(
    (t) => t.action_type === 'submit_form' || t.action_type === 'input_sales' || t.related_entity === 'sales_data');
  const warnaSkor = (v) => (v >= 80 ? 'text-[hsl(var(--success-text))]' : v >= 60 ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--danger-text))]');
  const judulUrut = (c) => (
    <Button variant="ghost" size="sm" className="-ml-2 h-7 px-2 font-medium text-muted-foreground" onClick={() => toggleSort(c.key)}
      data-testid={`daily-sort-${c.key}`} aria-label={`Urutkan menurut ${c.label}`}>
      {c.label}<ArrowUpDown className={sortKey === c.key ? 'text-[hsl(var(--primary))]' : 'opacity-40'} />
    </Button>
  );
  const kol = (key) => COLUMNS.find((c) => c.key === key);
  const kolom = [
    { kunci: 'account', label: judulUrut(kol('account')), hp: 'judul', isi: (acc) => (
      <div data-testid={`daily-acc-${acc.account_code}`}>
        <p className="font-medium text-foreground">{acc.account_name}</p>
        <p className="text-xs text-muted-foreground">{acc.account_code} · {labelPlatform(acc.platform)}</p>
      </div>) },
    { kunci: 'total', label: judulUrut(kol('total')), isi: (acc) => <YesNo ok={!!acc.sales_status?.entered_total} /> },
    { kunci: 'revenue', label: judulUrut(kol('revenue')), rata: 'kanan', isi: (acc) => (acc.sales_status?.entered_total
      ? <span className="tabular-nums md:whitespace-nowrap">{fmtRp(acc.sales_status.revenue)}</span> : <span className="text-muted-foreground">—</span>) },
    { kunci: 'orders', label: judulUrut(kol('orders')), rata: 'kanan', isi: (acc) => (acc.sales_status?.entered_total
      ? <span className="tabular-nums">{fmtNum(acc.sales_status.orders)}</span> : <span className="text-muted-foreground">—</span>) },
    { kunci: 'live', label: judulUrut(kol('live')), isi: (acc) => (
      <span data-testid={`daily-live-${acc.account_code}`}><YesNo ok={!!acc.sales_status?.entered_live} /></span>) },
    { kunci: 'health', label: judulUrut(kol('health')), rata: 'kanan', isi: (acc) => (acc.health_score == null
      ? <span className="text-muted-foreground">Belum ada</span>
      : <span className={`font-semibold tabular-nums ${warnaSkor(acc.health_score)}`}>{acc.health_score}</span>) },
    { kunci: 'tasks', label: judulUrut(kol('tasks')), rata: 'kanan', isi: (acc) => <span className="tabular-nums">{(acc.pending_action_tasks || []).length}</span> },
    { kunci: 'overdue', label: judulUrut(kol('overdue')), rata: 'kanan', isi: (acc) => (acc.overdue_count > 0
      ? <StatusBadge status="overdue" label={String(acc.overdue_count)} tone="danger" /> : <span className="tabular-nums text-muted-foreground">0</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (acc) => {
      const salesTask = salesTaskOf(acc);
      return !acc.sales_status?.entered_total && salesTask ? (
        <Button size="sm" onClick={() => setEksekusiTarget({ account: acc, task: salesTask })}
          data-testid={`eksekusi-btn-${acc.account_code}`}>
          <Zap />Eksekusi
        </Button>
      ) : <span className="text-muted-foreground">—</span>;
    } },
  ];

  return (
    <PageLayout testId="daily-report-module" title="Laporan harian"
      subtitle="Siapa sudah atau belum mengisi angka hari itu, per toko."
      filters={<>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" onClick={prevDay} data-testid="daily-prev-day" title="Hari sebelumnya" aria-label="Hari sebelumnya"><ChevronLeft /></Button>
          <div className="w-40"><DatePicker value={date} onChange={(v) => v && setDate(v)} bolehKosong={false} testId="daily-date-picker" /></div>
          <Button variant="outline" size="icon" onClick={nextDay} data-testid="daily-next-day" title="Hari berikutnya" aria-label="Hari berikutnya"><ChevronRight /></Button>
        </div>
        <div className="relative w-full sm:w-56">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="Cari toko, kode, platform" value={q} onChange={(e) => setQ(e.target.value)} data-testid="daily-search" />
        </div>
        <FilterChips value={onlyMissing ? 'belum' : ''} onChange={(v) => setOnlyMissing(v === 'belum')} hideWhenEmpty={false}
          testId="daily-only-missing"
          options={[{ key: '', label: 'Semua toko', count: accounts.length },
            { key: 'belum', label: 'Belum input', count: accounts.filter((a) => !a.sales_status?.entered_total).length }]} />
      </>}
      tools={<>
        <TombolUnduh namaBerkas={`laporan-harian-marketing-${date}`} namaLembar="Laporan harian" baris={rows} testId="daily-export-csv"
          kolom={[
            { label: 'Tanggal', nilai: () => formatTanggalID(date) }, { label: 'Toko', nilai: (a) => a.account_name },
            { label: 'Kode', nilai: (a) => a.account_code }, { label: 'Platform', nilai: (a) => labelPlatform(a.platform) },
            { label: 'Input harian', nilai: (a) => (a.sales_status?.entered_total ? 'Sudah' : 'Belum') },
            { label: 'Omzet diinput', nilai: (a) => Number(a.sales_status?.revenue || 0) },
            { label: 'Pesanan', nilai: (a) => Number(a.sales_status?.orders || 0) },
            { label: 'Input live', nilai: (a) => (a.sales_status?.entered_live ? 'Sudah' : 'Belum') },
            { label: 'Skor kesehatan', nilai: (a) => (a.health_score == null ? 'Belum ada' : a.health_score) },
            { label: 'Tugas menunggu', nilai: (a) => (a.pending_action_tasks || []).length },
            { label: 'Terlambat', nilai: (a) => Number(a.overdue_count || 0) },
          ]} />
        <ViewToggle value={view === 'cards' ? 'grid' : 'table'} onChange={(v) => setView(v === 'grid' ? 'cards' : 'table')} testId="daily-view" />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="daily-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={!loading && report && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="daily-kpi">
          <StatTile label="Tingkat input" value={`${(s.sales_input_rate || 0).toLocaleString('id-ID')}%`}
            sub={`${s.accounts_sales_entered || 0} dari ${s.accounts_total || 0} toko sudah input`}
            accent={s.sales_input_rate >= 80 ? 'success' : 'warning'} testId="daily-kpi-rate" />
          <StatTile label="Belum input" value={s.accounts_sales_missing || 0} accent={s.accounts_sales_missing > 0 ? 'danger' : 'default'}
            sub={`Toko tanpa omzet harian ${formatTanggalID(date)}`} testId="daily-kpi-missing" />
          <StatTile label="Tugas selesai" value={s.tasks_done_today || 0} sub="Diselesaikan pada tanggal ini" />
          <StatTile label="Tugas lewat batas" value={s.tasks_overdue || 0} accent={s.tasks_overdue > 0 ? 'danger' : 'default'}
            sub={`${s.tasks_pending_approval || 0} menunggu persetujuan`} />
        </div>
      )}>
      <NoStoreScopeNotice token={token} what="Daftar toko & angka di laporan ini" />

      {loading && !report ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat laporan…</p>
      ) : (
        <>
          {criticals.length > 0 && (
            <p className="flex items-start gap-1.5 text-sm text-[hsl(var(--danger-text))]" data-testid="daily-health-alert">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span><b>{criticals.length} akun kesehatannya kritis (skor di bawah 60):</b>{' '}
                {criticals.map((a) => `${a.account_name} ${a.health_score}`).join(' · ')}</span>
            </p>
          )}

          {view === 'table' ? (
            <TabelData kolom={kolom} baris={rows} kunci={(a) => a.account_id} testId="daily-table"
              kosong={<EmptyState icon={CalendarCheck} testId="daily-empty"
                title={accounts.length ? 'Tidak ada toko yang cocok' : 'Belum ada toko untuk tanggal ini'}
                description={accounts.length ? 'Ubah pencarian atau saringan.' : 'Toko yang Anda pegang akan muncul di sini.'} />} />
          ) : (
            <ul className="divide-y divide-[var(--glass-border)]" data-testid="daily-cards">
              {rows.map((acc) => {
                const st = acc.sales_status || {};
                const salesTask = salesTaskOf(acc);
                return (
                  <li key={acc.account_id} className="flex flex-wrap items-center gap-3 py-3" data-testid={`daily-card-${acc.account_code}`}>
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">{acc.account_name}</p>
                      <p className="text-sm text-muted-foreground">
                        Harian <YesNo ok={!!st.entered_total} /> · Live <YesNo ok={!!st.entered_live} />
                        {st.entered_total && <> · {fmtRp(st.revenue)} · {fmtNum(st.orders)} pesanan</>}
                      </p>
                    </div>
                    {acc.overdue_count > 0 && <StatusBadge status="overdue" label={`${acc.overdue_count} terlambat`} tone="danger" />}
                    {acc.health_score != null && <span className={`text-sm font-semibold ${warnaSkor(acc.health_score)}`}>{acc.health_score}</span>}
                    {!st.entered_total && salesTask && (
                      <Button size="sm" onClick={() => setEksekusiTarget({ account: acc, task: salesTask })}><Zap />Eksekusi</Button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          <p className="text-sm text-muted-foreground">
            Input harian = omzet total toko hari itu; input live = omzet dari sesi live (dinilai terpisah).{' '}
            <span data-testid="daily-count">{rows.length} toko ditampilkan{accounts.length !== rows.length ? ` dari ${accounts.length}` : ''}.</span>
          </p>

          {allPendingTasks.length > 0 && (
            <section className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-base font-semibold">Tugas menunggu aksi ({allPendingTasks.length})</p>
                <TombolUnduh namaBerkas={`tugas-menunggu-${date}`} namaLembar="Tugas" baris={allPendingTasks} testId="daily-tasks-unduh"
                  kolom={[
                    { label: 'Kode', nilai: (t) => t.task_code }, { label: 'Judul', nilai: (t) => t.title },
                    { label: 'Toko', nilai: (t) => t._account?.account_name || '' },
                    { label: 'Prioritas', nilai: (t) => PRIORITAS[t.priority]?.label || t.priority || '' },
                    { label: 'Jenis aksi', nilai: (t) => JENIS_AKSI[t.action_type] || t.action_type || '' },
                  ]} />
              </div>
              <TabelData baris={allPendingTasks} testId="daily-tasks-table"
                kolom={[
                  { kunci: 'judul', label: 'Tugas', hp: 'judul', isi: (t) => (
                    <div data-testid={`pending-task-${t.task_code}`}><p className="font-medium">{t.title}</p><p className="text-xs text-muted-foreground">{t.task_code}</p></div>) },
                  { kunci: 'toko', label: 'Toko', isi: (t) => t._account?.account_name || '—' },
                  { kunci: 'prio', label: 'Prioritas', isi: (t) => {
                    const p = PRIORITAS[t.priority] || { label: t.priority || '—', tone: 'muted' };
                    return <StatusBadge status={t.priority} label={p.label} tone={p.tone} />;
                  } },
                  { kunci: 'jenis', label: 'Jenis aksi', isi: (t) => JENIS_AKSI[t.action_type] || t.action_type || '—' },
                ]} />
            </section>
          )}
        </>
      )}

      {/* Popup input sales cepat (Eksekusi) */}
      {eksekusiTarget && (
        <QuickSalesDialog
          open={!!eksekusiTarget}
          onClose={() => setEksekusiTarget(null)}
          account={eksekusiTarget.account}
          task={eksekusiTarget.task}
          date={date}
          token={token}
          onSuccess={() => { setEksekusiTarget(null); load(); }}
        />
      )}
    </PageLayout>
  );
}

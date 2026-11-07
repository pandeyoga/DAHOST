/**
 * AccessoryValuationAutomation — FASE 10: dua otomasi valuasi aksesoris.
 *
 * MASALAH YANG DIPECAHKAN
 * 1) Item ber-HPP 0 hanya "ketahuan" saat orang kebetulan membuka tab Valuasi, atau
 *    lewat notifikasi PER-ITEM yang terpencar (12 item = 12 notifikasi, tanpa
 *    gambaran utuh). → Panel "Alarm belum dinilai": ringkasan harian 07:30 WIB,
 *    bisa dilihat & dikirim manual dari sini.
 * 2) Rapor valuasi harus diunduh manual tiap awal bulan; kalau lupa, tutup buku
 *    berjalan tanpa lampiran. → Panel "Rapor bulanan otomatis": kirim tanggal 1
 *    pukul 06:00 WIB ke email tim keuangan (lampiran Excel + PDF), lengkap dengan
 *    daftar penerima, status SMTP, tombol kirim sekarang, dan riwayat pengiriman.
 *
 * Endpoint: /api/acc/valuation/unvalued-digest[/send] · /api/acc/valuation/report-schedule[/send-now]
 *
 * Standar UI/UX v2 (8 Nov 2026): dibuka sebagai popup dari tab Valuasi HPP; warna token & StatusBadge,
 * tombol `Button`, isian bulan = pilihan bulan aplikasi (dulu input bulan bawaan browser), sakelar
 * aktif/nonaktif = Switch, riwayat = tabel + unduh.
 */

import { useState, useEffect, useCallback } from 'react';
import {
  BellRing, CalendarClock, Mail, Send, Loader2, CheckCircle2, AlertTriangle,
  RefreshCw, Users, History, Info, Clock, ChevronDown, ChevronRight,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { GlassCard } from '@/components/ui/glass';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { monthOptions } from '../finance/PeriodPicker';
import { Notice, StatTile, StatusBadge } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

async function api(method, path, token, body) {
  const opts = { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(`${API}${path}`, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
}

const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });
const fmtRp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;

function fmtDateTime(iso) {
  if (!iso) return '-';
  try {
    // Selalu tampilkan dalam WIB: jadwal job memang berjalan di Asia/Jakarta, jadi
    // memakai zona browser (mis. UTC di server QA) membuat "01 Agu 06:00" terbaca
    // "31 Jul 23:00" dan membingungkan.
    return `${new Date(iso).toLocaleString('id-ID', {
      day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
      timeZone: 'Asia/Jakarta',
    })} WIB`;
  } catch { return String(iso).slice(0, 16); }
}

const MONTHS_ID = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli',
  'Agustus', 'September', 'Oktober', 'November', 'Desember'];

function periodLabel(m) {
  if (!m) return 'Semua periode';
  const [y, mo] = String(m).split('-');
  return `${MONTHS_ID[Number(mo) - 1] || mo} ${y}`;
}

// 2026-11-08: pilihan bulan aplikasi (dulu isian bulan bawaan browser)
const MONTH_OPTIONS = monthOptions(24);

const RUN_STATUS = {
  sent: { label: 'Terkirim', tone: 'success' },
  partial: { label: 'Sebagian', tone: 'warning' },
  failed: { label: 'Gagal', tone: 'danger' },
  skipped_already_sent: { label: 'Sudah pernah', tone: 'muted' },
  skipped_no_smtp: { label: 'Email belum diatur', tone: 'warning' },
  no_recipients: { label: 'Tanpa penerima', tone: 'warning' },
};

function StatusPill({ status }) {
  const s = RUN_STATUS[status] || { label: 'Lainnya', tone: 'muted' };
  return <StatusBadge status={status} label={s.label} tone={s.tone} />;
}

export default function AccessoryValuationAutomation({ token, onChanged }) {
  const [digest, setDigest] = useState(null);
  const [sched, setSched] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [extra, setExtra] = useState('');
  const [reportMonth, setReportMonth] = useState('');
  const [openHistory, setOpenHistory] = useState(false);

  // `keepFeedback` WAJIB dipakai saat load() dipanggil dari sebuah aksi (kirim
  // digest / simpan jadwal / kirim rapor). Tanpa itu, `setErr('')` di sini
  // MENGHAPUS pesan yang baru saja di-set aksi tersebut — bug nyata: klik
  // "Kirim rapor sekarang" tanpa SMTP tidak menampilkan penjelasan apa pun.
  const load = useCallback(async (keepFeedback = false) => {
    setLoading(true);
    if (!keepFeedback) { setErr(''); setMsg(''); }
    try {
      const [d, s] = await Promise.all([
        api('GET', '/api/acc/valuation/unvalued-digest', token),
        api('GET', '/api/acc/valuation/report-schedule', token),
      ]);
      setDigest(d);
      setSched(s);
      setExtra((s.extra_emails || []).join(', '));
      setReportMonth((m) => m || s.default_month || '');
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const sendDigest = async () => {
    setBusy('digest'); setErr(''); setMsg('');
    try {
      const r = await api('POST', '/api/acc/valuation/unvalued-digest/send', token);
      setMsg(r.sent
        ? `Ringkasan ${r.items} item belum dinilai dikirim ke ${r.sent} penanggung jawab.`
        : `Tidak ada yang dikirim — ${r.skipped}`);
      await load(true);
    } catch (e) { setErr(e.message); }
    finally { setBusy(''); }
  };

  const saveSchedule = async (patch) => {
    setBusy('schedule'); setErr(''); setMsg('');
    try {
      const r = await api('PUT', '/api/acc/valuation/report-schedule', token, patch);
      setMsg(patch.enabled === false
        ? 'Rapor otomatis dimatikan. Rapor tetap bisa diunduh/kirim manual.'
        : `Pengaturan disimpan · ${r.recipients?.length || 0} penerima aktif.`);
      await load(true);
    } catch (e) { setErr(e.message); }
    finally { setBusy(''); }
  };

  const sendReport = async () => {
    setBusy('report'); setErr(''); setMsg('');
    try {
      const qs = reportMonth ? `?month=${reportMonth}` : '';
      const r = await api('POST', `/api/acc/valuation/report-schedule/send-now${qs}`, token);
      if (r.status === 'sent') setMsg(r.message);
      else if (r.status === 'skipped_no_smtp') setErr(r.message);
      else if (r.status === 'no_recipients') setErr(r.message);
      else setErr(r.message || `Status: ${(RUN_STATUS[r.status] || {}).label || r.status}`);
      await load(true);
      onChanged?.();
    } catch (e) { setErr(e.message); }
    finally { setBusy(''); }
  };

  // Muat awal saja yang menampilkan tulisan memuat. Saat memuat ulang setelah aksi, panel tetap
  // tampil (kalau tidak, banner hasil aksi ikut hilang dari layar).
  if (loading && !digest && !sched) {
    return <p className="py-10 text-center text-sm text-muted-foreground" data-testid="acc-val-automation-loading">Memuat pengaturan otomasi…</p>;
  }

  const dt = digest?.totals || {};
  const smtp = sched?.smtp || {};
  const recipients = sched?.recipients || [];
  const runs = sched?.runs || [];
  const pilihanBulan = reportMonth && !MONTH_OPTIONS.some((o) => o.value === reportMonth)
    ? [{ value: reportMonth, label: periodLabel(reportMonth) }, ...MONTH_OPTIONS] : MONTH_OPTIONS;

  return (
    <div className="space-y-3" data-testid="acc-val-automation">
      {err && <Notice tone="danger" testId="acc-val-auto-error">{err}</Notice>}
      {msg && <Notice tone="success" testId="acc-val-auto-msg">{msg}</Notice>}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* ── PANEL 1: ALARM / RINGKASAN HARIAN ─────────────────────────── */}
        <GlassCard className="space-y-3 p-4" data-testid="acc-digest-panel">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-2">
              <BellRing className="mt-0.5 h-4 w-4 text-[hsl(var(--warning-text))]" />
              <div>
                <p className="text-base font-semibold">Alarm item belum dinilai</p>
                <p className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  {digest?.schedule_label || 'Setiap hari pukul 07:30 (Asia/Jakarta)'}
                </p>
              </div>
            </div>
            <Button variant="outline" size="icon-sm" onClick={() => load()} title="Muat ulang" aria-label="Muat ulang"
              data-testid="acc-digest-refresh">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
          </div>

          {dt.items > 0 ? (
            <>
              <div className="grid grid-cols-3 gap-2">
                <StatTile label="Item HPP 0" value={fmtNum(dt.items)} accent="warning" testId="acc-digest-count" />
                <StatTile label="Punya stok" value={fmtNum(dt.items_with_stock)} />
                <StatTile label={`Mutasi ${digest?.window_hours || 24} jam`} value={fmtNum(dt.movements_window)} />
              </div>

              <ul className="divide-y divide-[var(--glass-border)] text-sm" data-testid="acc-digest-list">
                {(digest?.items || []).slice(0, 6).map((it) => (
                  <li key={it.id} className="flex items-center justify-between gap-2 py-1.5">
                    <span className="min-w-0 truncate">
                      <span className="text-xs text-muted-foreground">{it.code}</span>{' '}{it.name}
                    </span>
                    <span className="flex shrink-0 items-center gap-1 text-muted-foreground">
                      {fmtNum(it.stock_qty)} {it.unit}
                      {it.movements_window > 0 && (
                        <StatusBadge status="mutasi" label={`${it.movements_window} mutasi`} tone="warning" />
                      )}
                    </span>
                  </li>
                ))}
                {(digest?.items || []).length > 6 && (
                  <li className="py-1.5 text-muted-foreground">… dan {digest.items.length - 6} item lain</li>
                )}
              </ul>
            </>
          ) : (
            <Notice tone="success" icon={CheckCircle2} testId="acc-digest-clean">
              Semua aksesoris sudah punya HPP — tidak ada alarm.
            </Notice>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <p className="text-xs text-muted-foreground">
              {digest?.last_digest
                ? `Ringkasan terakhir: ${fmtDateTime(digest.last_digest.created_at)} · ${digest.last_digest.count || 0} item`
                : 'Belum pernah mengirim ringkasan.'}
            </p>
            <Button onClick={sendDigest} disabled={busy === 'digest' || !dt.items} data-testid="acc-digest-send">
              {busy === 'digest' ? <Loader2 className="animate-spin" /> : <Send />}
              Kirim ringkasan sekarang
            </Button>
          </div>
          <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3 w-3 shrink-0" />
            Satu notifikasi berisi semua item tanpa harga (bukan satu per item). Alarm per item
            saat mutasi tetap berjalan, dibatasi 1×/24 jam per item.
          </p>
        </GlassCard>

        {/* ── PANEL 2: RAPOR BULANAN OTOMATIS ───────────────────────────── */}
        <GlassCard className="space-y-3 p-4" data-testid="acc-report-schedule-panel">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-2">
              <CalendarClock className="mt-0.5 h-4 w-4 text-[hsl(var(--primary))]" />
              <div>
                <p className="text-base font-semibold">Rapor bulanan otomatis ke keuangan</p>
                <p className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  {sched?.schedule_label || 'Setiap tanggal 1 pukul 06:00 (Asia/Jakarta)'}
                  {sched?.next_run_at && ` · berikutnya ${fmtDateTime(sched.next_run_at)}`}
                </p>
              </div>
            </div>
            <label className="flex shrink-0 items-center gap-2 text-sm" htmlFor="acc-report-toggle">
              <Switch id="acc-report-toggle" checked={!!sched?.enabled} disabled={busy === 'schedule'}
                onCheckedChange={(v) => saveSchedule({ enabled: v })} data-testid="acc-report-toggle" />
              {sched?.enabled ? 'Aktif' : 'Nonaktif'}
            </label>
          </div>

          {/* Status SMTP */}
          <Notice tone={smtp.configured ? 'success' : 'warning'} icon={smtp.configured ? Mail : AlertTriangle}
            testId="acc-report-smtp-status">
            {smtp.configured ? (
              <>Email siap: <strong>{smtp.host}:{smtp.port}</strong> ({smtp.security}
                {smtp.auth ? ', dengan login' : ', tanpa login'}) · pengirim {smtp.from_email || '-'}</>
            ) : (
              <>Email (SMTP) belum diatur — rapor tetap dibuat & dikirim sebagai notifikasi aplikasi,
                tapi lampiran belum bisa dikirim lewat email. Atur di{' '}
                <a href="#maklon-notifications" className="font-medium underline">
                  Pusat Notifikasi › Pengaturan › Email (SMTP)</a>.</>
            )}
            {smtp.note && <div className="mt-0.5">{smtp.note}</div>}
          </Notice>

          {/* Penerima */}
          <div className="space-y-1.5">
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Users className="h-4 w-4" /> Penerima ({recipients.length})
            </p>
            <div className="flex flex-wrap gap-1.5" data-testid="acc-report-recipients">
              {recipients.length === 0 && (
                <span className="text-sm text-[hsl(var(--warning-text))]">
                  Belum ada penerima — tambahkan email di bawah atau isi email pada pengguna peran keuangan.
                </span>
              )}
              {recipients.map((r) => (
                <span key={r.email} title={r.source === 'role_keuangan' ? 'Pengguna peran keuangan' : 'Email tambahan'}>
                  <StatusBadge status={r.source} label={r.email} tone={r.source === 'role_keuangan' ? 'info' : 'primary'} />
                </span>
              ))}
            </div>
          </div>

          {/* Email tambahan */}
          <div className="space-y-1.5">
            <label className="block text-sm font-medium" htmlFor="acc-report-extra">
              Email tambahan (pisahkan dengan koma)
            </label>
            <div className="flex gap-2">
              <Input id="acc-report-extra" value={extra} onChange={(e) => setExtra(e.target.value)}
                placeholder="pajak@perusahaan.id, arsip@perusahaan.id" className="min-w-0 flex-1"
                data-testid="acc-report-extra-emails" />
              <Button variant="success" onClick={() => saveSchedule({ extra_emails: extra })} disabled={busy === 'schedule'}
                data-testid="acc-report-extra-save">
                {busy === 'schedule' ? <Loader2 className="animate-spin" /> : 'Simpan'}
              </Button>
            </div>
          </div>

          {/* Kirim sekarang */}
          <div className="space-y-1.5 border-t border-[var(--glass-border)] pt-3">
            <label className="block text-sm font-medium" htmlFor="acc-report-month">Periode rapor</label>
            <div className="flex flex-wrap items-center gap-2">
              <SmartNativeSelect id="acc-report-month" value={reportMonth} onChange={(e) => setReportMonth(e.target.value)}
                className="w-44" data-testid="acc-report-month">
                {pilihanBulan.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </SmartNativeSelect>
              <Button onClick={sendReport} disabled={busy === 'report'} data-testid="acc-report-send-now">
                {busy === 'report' ? <Loader2 className="animate-spin" /> : <Send />}
                Kirim rapor sekarang
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Lampiran Excel + PDF · bawaan periode {periodLabel(sched?.default_month)}
            </p>
          </div>

          {/* Riwayat */}
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Button variant="link" size="sm" className="px-0" onClick={() => setOpenHistory((v) => !v)}
                aria-expanded={openHistory} data-testid="acc-report-history-toggle">
                {openHistory ? <ChevronDown /> : <ChevronRight />}
                <History /> Riwayat pengiriman ({runs.length})
              </Button>
              {openHistory && runs.length > 0 && (
                <TombolUnduh namaBerkas="riwayat-rapor-valuasi" namaLembar="Riwayat" baris={runs} testId="acc-report-history-unduh"
                  kolom={[
                    { label: 'Waktu', nilai: (r) => fmtDateTime(r.created_at) },
                    { label: 'Periode', nilai: (r) => periodLabel(r.month) },
                    { label: 'Status', nilai: (r) => (RUN_STATUS[r.status] || {}).label || r.status },
                    { label: 'Terkirim', nilai: (r) => Number(r.sent_count || 0) },
                    { label: 'Gagal', nilai: (r) => Number(r.failed_count || 0) },
                    { label: 'Nilai persediaan (Rp)', nilai: (r) => Number(r.total_value || 0) },
                    { label: 'Pemicu', nilai: (r) => r.triggered_by || '' },
                  ]} />
              )}
            </div>
            {openHistory && (
              <div data-testid="acc-report-history">
                {runs.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Belum ada pengiriman.</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Waktu</TableHead>
                        <TableHead>Periode</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="text-right">Terkirim</TableHead>
                        <TableHead>Pemicu</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {runs.slice(0, 8).map((r) => (
                        <TableRow key={r.id}>
                          <TableCell className="whitespace-nowrap">{fmtDateTime(r.created_at)}</TableCell>
                          <TableCell>{periodLabel(r.month)}</TableCell>
                          <TableCell><StatusPill status={r.status} /></TableCell>
                          <TableCell className="text-right tabular-nums">
                            {r.sent_count || 0}
                            {r.failed_count ? <span className="text-[hsl(var(--danger-text))]"> / {r.failed_count} gagal</span> : ''}
                            {r.total_value ? <div className="text-xs text-muted-foreground">{fmtRp(r.total_value)}</div> : null}
                          </TableCell>
                          <TableCell className="max-w-[10rem] truncate" title={r.triggered_by}>{r.triggered_by}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </div>
            )}
          </div>
        </GlassCard>
      </div>
    </div>
  );
}

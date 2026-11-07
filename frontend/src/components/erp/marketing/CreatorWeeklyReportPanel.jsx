/**
 * CreatorWeeklyReportPanel — RAPOR KREATOR MINGGUAN (sesi #35).
 *
 * Kenapa ada: insentif dihitung per periode 3 bulan dan performa dibaca per bulan.
 * Keduanya benar untuk MEMBAYAR, tetapi terlambat untuk MENGARAHKAN — kreator baru
 * tahu dia tertinggal saat periodenya hampir habis. Rapor 7 hari bergulir menjawab
 * "pekan ini saya menghasilkan apa, target periode saya sejauh mana".
 *
 * Aturan yang kelihatan di layar:
 *   · GMV (angka platform) & omzet pesanan berdampingan, TIDAK dijumlah.
 *   · Nominal insentif dibaca dari layar Insentif (satu sumber), bukan dihitung ulang.
 *   · Pengiriman idempoten per (kreator, pekan) — tombol berubah jadi "Kirim ulang".
 *   · Kalau SMTP belum diisi, rapor tetap tersimpan & bisa dibaca kreator di portalnya.
 *
 * Standar UI/UX v2 (8 Nov 2026): tampil di dalam Kelola KOL (tanpa kepala sendiri); pekan = DatePicker (dulu input
 * tanggal bawaan), 4 StatTile (dulu 6 kartu), tabel + unduh, label Indonesia. Panggilan API tidak berubah.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { Loader2, RefreshCw, Send, Info, Mail, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import DatePicker from '@/components/ui/date-picker';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatRupiah, formatDateID } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const fmtNum = (n) => new Intl.NumberFormat('id-ID').format(Math.round(n || 0));
const rp = formatRupiah;

const STATUS_LABEL = {
  sent: 'Terkirim', failed: 'Gagal kirim', no_email: 'Belum punya email',
  skipped_no_smtp: 'Email pengirim belum diatur', already_sent: 'Sudah dikirim',
};

export default function CreatorWeeklyReportPanel({ token }) {
  const authH = useMemo(
    () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const [weekEnd, setWeekEnd] = useState(() => todayWIB());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState('');

  const todayStr = todayWIB();
  // Atribut `max` hanya membatasi picker, bukan tanggal yang DIKETIK — pekan masa
  // depan selalu bernilai 0 dan terbaca sebagai "kreator tidak bekerja".
  const setWeek = (v) => setWeekEnd(v && v > todayStr ? todayStr : (v || todayStr));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(
        `${API}/api/marketing/kol/weekly-report?week_end=${weekEnd}`, { headers: authH });
      setData(res.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Gagal memuat rapor mingguan');
      setData(null);
    } finally { setLoading(false); }
  }, [weekEnd, authH]);

  useEffect(() => { load(); }, [load]);

  const send = async (creatorId, force) => {
    setSending(creatorId || 'all');
    try {
      const res = await axios.post(`${API}/api/marketing/kol/weekly-report/send`,
        { week_end: weekEnd, creator_ids: creatorId ? [creatorId] : [], force: !!force },
        { headers: authH });
      const s = res.data.summary || {};
      toast.success(`Rapor: ${s.sent || 0} terkirim · ${s.skipped_no_smtp || 0} tanpa SMTP `
        + `· ${s.no_email || 0} tanpa email · ${s.failed || 0} gagal`);
      if (!res.data.smtp_configured) {
        toast.info('SMTP belum dikonfigurasi — rapor tersimpan & bisa dibaca kreator di portalnya.');
      }
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Gagal mengirim rapor');
    } finally { setSending(''); }
  };

  const t = data?.totals || {};
  const rows = data?.rows || [];
  const period = data?.period || {};

  const TIPE = { new: 'Baru', kontrak: 'Kontrak', continue: 'Lanjutan' };
  const tgl = (v) => (v ? formatDateID(v) : '—');
  const pct = (n) => `${Number(n || 0).toFixed(2).replace('.', ',')}%`;
  const statusKirim = (last) => (last
    ? <span title={last.error || ''}><StatusBadge status={last.status} label={STATUS_LABEL[last.status] || 'Lainnya'} tone={last.status === 'sent' ? 'success' : 'warning'} /></span>
    : <span className="text-muted-foreground">Belum dikirim</span>);
  const kolom = [
    { kunci: 'kreator', label: 'Kreator', hp: 'judul', isi: (r) => (
      <div data-testid={`weekly-row-${r.creator_id}`}>
        <p className="font-medium">{r.creator_name}</p>
        <p className="text-xs text-muted-foreground">{r.creator_code} · {TIPE[r.creator_type] || r.creator_type}{r.domicile ? ` · ${r.domicile}` : ''}</p>
        {!r.login_email && <p className="inline-flex items-center gap-1 text-xs text-[hsl(var(--warning-text))]"><AlertTriangle className="h-3 w-3" />belum ada email portal</p>}
      </div>) },
    { kunci: 'konten', label: 'Konten / tayang', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtNum(r.contents)} / {fmtNum(r.posted)}</span> },
    { kunci: 'views', label: 'Tayangan', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums">{fmtNum(r.views)}<span className="block text-xs text-muted-foreground">interaksi {fmtNum(r.engagement)} · {pct(r.engagement_rate)}</span></span>) },
    { kunci: 'gmv', label: 'GMV (KPI)', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums font-medium md:whitespace-nowrap">{rp(r.gmv_kpi)}<span className="block text-xs font-normal text-muted-foreground">{fmtNum(r.orders_kpi)} pesanan KPI</span></span>) },
    { kunci: 'omzet', label: 'Omzet pesanan', rata: 'kanan', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{rp(r.order_revenue)}</span> },
    { kunci: 'pcs', label: 'Pcs pekan / target', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums md:whitespace-nowrap">{fmtNum(r.pcs_week)}<span className="block text-xs text-muted-foreground">
        {r.target_pcs ? `periode ${fmtNum(r.pcs_period)} / ${fmtNum(r.target_pcs)} (${r.target_progress_pct}%)` : 'tanpa target'}</span></span>) },
    { kunci: 'insentif', label: 'Insentif', rata: 'kanan', isi: (r) => (r.incentive_eligible
      ? <span className="tabular-nums md:whitespace-nowrap">{rp(r.incentive_total)}</span> : <span className="text-muted-foreground">tipe baru</span>) },
    { kunci: 'status', label: 'Status kirim', isi: (r) => statusKirim(r.last_sent) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <Button size="sm" variant="outline" onClick={() => send(r.creator_id, !!r.last_sent)} disabled={sending === r.creator_id}
        data-testid={`weekly-send-${r.creator_id}`}>
        {sending === r.creator_id ? <Loader2 className="animate-spin" /> : <Mail />}{r.last_sent ? 'Kirim ulang' : 'Kirim'}
      </Button>) },
  ];

  return (
    <div className="space-y-4" data-testid="creator-weekly-report-panel">
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-48">
          <DatePicker value={weekEnd} onChange={(v) => setWeek(v)} max={todayStr} bolehKosong={false} testId="weekly-week-end" />
        </div>
        <p className="text-sm text-muted-foreground">Pekan berakhir · 7 hari: <span className="font-medium text-foreground">{tgl(period.start)} – {tgl(period.end)}</span></p>
        <div className="ml-auto flex items-center gap-2">
          <TombolUnduh namaBerkas={`rapor-kreator-${weekEnd}`} namaLembar="Rapor" baris={rows} testId="weekly-unduh"
            kolom={[
              { label: 'Kreator', nilai: (r) => r.creator_name }, { label: 'Kode', nilai: (r) => r.creator_code || '' },
              { label: 'Tipe', nilai: (r) => TIPE[r.creator_type] || r.creator_type || '' },
              { label: 'Konten', nilai: (r) => Number(r.contents) || 0 }, { label: 'Tayang', nilai: (r) => Number(r.posted) || 0 },
              { label: 'Tayangan', nilai: (r) => Number(r.views) || 0 }, { label: 'Interaksi', nilai: (r) => Number(r.engagement) || 0 },
              { label: 'Pesanan (KPI)', nilai: (r) => Number(r.orders_kpi) || 0 }, { label: 'GMV (KPI)', nilai: (r) => Number(r.gmv_kpi) || 0 },
              { label: 'Omzet pesanan', nilai: (r) => Number(r.order_revenue) || 0 }, { label: 'Pcs pekan', nilai: (r) => Number(r.pcs_week) || 0 },
              { label: 'Pcs periode', nilai: (r) => Number(r.pcs_period) || 0 }, { label: 'Target pcs', nilai: (r) => r.target_pcs || '' },
              { label: 'Insentif', nilai: (r) => (r.incentive_eligible ? Number(r.incentive_total) || 0 : '') },
              { label: 'Status kirim', nilai: (r) => (r.last_sent ? STATUS_LABEL[r.last_sent.status] || '' : 'Belum dikirim') },
            ]} />
          <Button size="icon" variant="outline" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="weekly-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
          <Button onClick={() => send(null, false)} disabled={!!sending || !rows.length} data-testid="weekly-send-all">
            {sending === 'all' ? <Loader2 className="animate-spin" /> : <Send />}Kirim semua
          </Button>
        </div>
      </div>

      {data && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="weekly-kpi">
          <StatTile label="Kreator" value={fmtNum(t.creators)} sub={`${fmtNum(t.creators_active)} aktif berkonten`} hint="Kreator yang dilaporkan pekan ini." />
          <StatTile label="Konten pekan ini" value={fmtNum(t.contents)} sub={`${fmtNum(t.posted)} tayang · ${fmtNum(t.views)} tayangan`} />
          <StatTile label="GMV (KPI platform)" value={rp(t.gmv_kpi)} sub={`Omzet pesanan ${rp(t.order_revenue)}`}
            hint="Dua sumber berbeda — berdampingan, tidak dijumlah." />
          <StatTile label="Insentif periode" value={rp(t.incentive_total)} sub={`${fmtNum(t.pcs_week)} pcs pekan ini`} hint="Dibaca dari layar Insentif (satu sumber)." />
        </div>
      )}

      {loading && !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Menyusun rapor mingguan…</p>
      ) : (
        <TabelData kolom={kolom} baris={rows} kunci={(r) => r.creator_id} testId="weekly-table"
          kosong={<EmptyState testId="weekly-empty" title="Belum ada kreator yang bisa dilaporkan" />} />
      )}

      {(data?.data_notes || []).length > 0 && (
        <Notice tone="info" icon={Info} title="Catatan kejujuran data" testId="weekly-notes">
          <ul className="list-disc space-y-0.5 pl-4">{(data.data_notes || []).map((n, i) => <li key={i}>{n}</li>)}</ul>
        </Notice>
      )}
    </div>
  );
}

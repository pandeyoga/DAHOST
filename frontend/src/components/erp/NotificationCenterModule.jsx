/**
 * Notifikasi (Portal Toko › maklon-notifications, juga Portal Sistem) — outbox pesan ke klien (WhatsApp & email),
 * konfigurasi penyedia, dan job terjadwal.
 *
 * Standar UI/UX v2 (8 Nov 2026): tab halaman = HubTabs (dulu deret tombol bergaris bawah buatan sendiri);
 * daftar notifikasi = tabel (dulu kartu per baris) + unduh Excel/CSV + detail popup; konfigurasi penyedia dibaca
 * di halaman dan diubah lewat FormPopup (dulu form panjang di halaman); job = tabel. Kartu angka = StatTile (maks 4).
 * Panggilan API, isian, dan isi yang disimpan tidak berubah.
 * Perbaikan ikut: isian konfigurasi dulu kehilangan fokus setiap huruf diketik (komponen dibuat ulang tiap render).
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  RefreshCw, Send, Trash2, RotateCw, AlertTriangle, Mail, MessageCircle, Search, PlayCircle, Settings,
  TestTube, CheckCircle2, XCircle, WifiOff,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { GlassCard } from '@/components/ui/glass';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatDateTimeID } from '@/lib/format';
import HubTabs from './hubs/HubTabs';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';

const CHANNEL_ICON = { whatsapp: MessageCircle, email: Mail };
const CHANNEL_LABEL = { whatsapp: 'WhatsApp', email: 'Email' };
const STATUS = {
  queued: { label: 'Menunggu kirim', tone: 'warning' },
  sent: { label: 'Terkirim', tone: 'success' },
  failed: { label: 'Gagal', tone: 'danger' },
};
const statusN = (s) => STATUS[s] || { label: s || '—', tone: 'muted' };
const EVENT_LABEL = {
  sample_submitted: 'Sample siap disetujui',
  invoice_issued: 'Faktur baru',
  invoice_overdue: 'Faktur lewat jatuh tempo',
  revision_requested: 'Revisi diminta',
  stage_change: 'Perubahan tahap produksi',
  manual: 'Manual',
};
const labelEvent = (e) => EVENT_LABEL[e] || 'Lainnya';
const waktu = (v) => {
  if (!v) return '—';
  const s = String(v);
  const d = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(s) ? s : `${s}Z`);
  return Number.isNaN(d.getTime()) ? '—' : formatDateTimeID(d);
};
const ya = (v) => (v ? 'Ya' : 'Tidak');

// ─── TAB 1 · NOTIFIKASI ─────────────────────────────────────────────────────
function NotifListTab({ headers, summary, onChanged, goConfig }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterChannel, setFilterChannel] = useState('all');
  const [filterEvent, setFilterEvent] = useState('all');
  const [search, setSearch] = useState('');
  const [bulkSending, setBulkSending] = useState(false);
  const [detail, setDetail] = useState(null);

  const params = useCallback((limit) => {
    const p = new URLSearchParams();
    if (filterStatus !== 'all') p.set('status', filterStatus);
    if (filterChannel !== 'all') p.set('channel', filterChannel);
    if (filterEvent !== 'all') p.set('event_type', filterEvent);
    if (limit) p.set('limit', String(limit));
    return p;
  }, [filterStatus, filterChannel, filterEvent]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r1 = await fetch(`/api/dewi/notifications?${params()}`, { headers });
      if (r1.ok) setItems(await r1.json());
    } finally { setLoading(false); }
    onChanged?.();
  }, [params, headers, onChanged]);

  useEffect(() => { load(); }, [load]);

  const markSent = async (id) => {
    const r = await fetch(`/api/dewi/notifications/${id}/send`, { method: 'POST', headers });
    const d = await r.json();
    if (r.ok) {
      toast.success(d.real ? 'Dikirim lewat penyedia sungguhan.' : 'Ditandai terkirim (mode uji, tidak dikirim sungguhan).');
      setDetail(null);
      load();
    } else toast.error('Gagal mengirim notifikasi.');
  };
  const retry = async (id) => {
    const r = await fetch(`/api/dewi/notifications/${id}/retry`, { method: 'POST', headers });
    if (r.ok) { toast.success('Notifikasi diantrekan ulang.'); setDetail(null); load(); }
  };
  const remove = async (id) => {
    if (!(await confirmDialog({ title: 'Hapus notifikasi ini?', body: 'Catatan pesan ini hilang dari outbox.', confirmLabel: 'Hapus', danger: true }))) return;
    const r = await fetch(`/api/dewi/notifications/${id}`, { method: 'DELETE', headers });
    if (r.ok) { toast.success('Notifikasi dihapus.'); setDetail(null); load(); }
  };
  const bulkSend = async () => {
    setBulkSending(true);
    try {
      const r = await fetch('/api/dewi/notifications/bulk-send', { method: 'POST', headers });
      const d = await r.json();
      if (r.ok) {
        toast.success(`Kirim semua: ${d.sent} terkirim, ${d.failed} gagal, ${d.skipped} dilewati.`);
        load();
      }
    } catch (e) { toast.error(e.message); }
    finally { setBulkSending(false); }
  };
  const scanOverdue = async () => {
    const r = await fetch('/api/dewi/notifications/scan-overdue', { method: 'POST', headers });
    if (r.ok) {
      const d = await r.json();
      toast.success(`Pindai selesai: ${d.queued} notifikasi baru dari ${d.invoices_checked} faktur.`);
      load();
    }
  };

  const cocok = (n, q) => !q || (n.recipient || '').toLowerCase().includes(q)
    || (n.body || '').toLowerCase().includes(q) || (n.subject || '').toLowerCase().includes(q);
  const q = search.trim().toLowerCase();
  const filtered = useMemo(() => items.filter((n) => cocok(n, q)), [items, q]);
  // Jumlah menunggu = hitungan server (semua notifikasi), bukan hanya 100 baris yang dimuat — "Kirim semua" mengirim semuanya.
  const queuedCount = summary?.by_status?.queued ?? items.filter((n) => n.status === 'queued').length;
  const terpotong = items.length >= 100;

  const aksiBaris = (n) => (
    <div className="flex items-center justify-end gap-1">
      {n.status === 'queued' && <Button size="sm" variant="outline" onClick={() => markSent(n.id)}><Send />Kirim</Button>}
      {n.status === 'failed' && <Button size="sm" variant="outline" onClick={() => retry(n.id)}><RotateCw />Ulangi</Button>}
      <Button size="icon-sm" variant="ghost" className="text-[hsl(var(--danger-text))]" onClick={() => remove(n.id)}
        title="Hapus notifikasi" aria-label="Hapus notifikasi"><Trash2 /></Button>
    </div>
  );

  const kolom = [
    { kunci: 'penerima', label: 'Penerima', hp: 'judul', isi: (n) => {
      const Icon = CHANNEL_ICON[n.channel] || Mail;
      return (
        <span className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-label={CHANNEL_LABEL[n.channel] || n.channel} />
          <span className="truncate font-medium text-foreground">{n.recipient}</span>
        </span>);
    } },
    { kunci: 'jenis', label: 'Jenis', isi: (n) => <span className="text-sm md:whitespace-nowrap">{labelEvent(n.event_type)}</span> },
    { kunci: 'isi', label: 'Isi pesan', hp: 'keterangan', isi: (n) => (
      <div className="min-w-0 md:max-w-[26rem]">
        {n.subject && <p className="truncate text-sm font-medium">{n.subject}</p>}
        <p className="line-clamp-2 text-xs text-muted-foreground">{n.body}</p>
      </div>) },
    { kunci: 'status', label: 'Status', isi: (n) => (
      <span className="flex flex-wrap gap-1">
        <StatusBadge status={n.status} label={statusN(n.status).label} tone={statusN(n.status).tone} />
        {n.sent_mock && <StatusBadge status="uji" label="Mode uji" tone="muted" />}
      </span>) },
    { kunci: 'dibuat', label: 'Dibuat', isi: (n) => <span className="tabular-nums md:whitespace-nowrap">{waktu(n.created_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: aksiBaris },
  ];

  const kolomUnduh = [
    { label: 'Penerima', nilai: (n) => n.recipient },
    { label: 'Saluran', nilai: (n) => CHANNEL_LABEL[n.channel] || n.channel },
    { label: 'Jenis', nilai: (n) => labelEvent(n.event_type) },
    { label: 'Subjek', nilai: (n) => n.subject || '' },
    { label: 'Isi', nilai: (n) => n.body || '' },
    { label: 'Status', nilai: (n) => statusN(n.status).label },
    { label: 'Dikirim sungguhan', nilai: (n) => (n.sent_real ? 'Ya' : n.sent_mock ? 'Tidak (mode uji)' : '') },
    { label: 'Dibuat', nilai: (n) => waktu(n.created_at) },
    { label: 'Dikirim', nilai: (n) => (n.sent_at ? waktu(n.sent_at) : '') },
  ];
  const ambilSemua = async () => {
    const r = await fetch(`/api/dewi/notifications?${params(5000)}`, { headers });
    const d = r.ok ? await r.json() : [];
    return (Array.isArray(d) ? d : []).filter((n) => cocok(n, q));
  };
  const providerAktif = summary && (summary.whatsapp_configured || summary.email_configured);
  const adaSaring = filterStatus !== 'all' || filterChannel !== 'all' || filterEvent !== 'all' || !!q;

  return (
    <PageLayout testId="notif-list-tab" title="Notifikasi"
      subtitle="Pesan otomatis ke klien (WhatsApp & email) saat tahap produksi berubah, faktur terbit, dan lainnya."
      actions={<>
        <Button variant="outline" onClick={scanOverdue} data-testid="notif-scan-overdue"><AlertTriangle />Pindai faktur lewat jatuh tempo</Button>
        {queuedCount > 0 && (
          <Button onClick={bulkSend} disabled={bulkSending} data-testid="notif-bulk-send">
            <Send />{bulkSending ? 'Mengirim…' : `Kirim semua (${queuedCount})`}
          </Button>
        )}
      </>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari penerima atau isi" className="pl-8"
            data-testid="notif-search" />
        </div>
        <SmartNativeSelect value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="w-40" searchable={false}
          data-testid="notif-filter-status">
          <option value="all">Semua status</option>
          <option value="queued">Menunggu kirim</option>
          <option value="sent">Terkirim</option>
          <option value="failed">Gagal</option>
        </SmartNativeSelect>
        <SmartNativeSelect value={filterChannel} onChange={(e) => setFilterChannel(e.target.value)} className="w-40" searchable={false}
          data-testid="notif-filter-channel">
          <option value="all">Semua saluran</option>
          <option value="whatsapp">WhatsApp</option>
          <option value="email">Email</option>
        </SmartNativeSelect>
        <SmartNativeSelect value={filterEvent} onChange={(e) => setFilterEvent(e.target.value)} className="w-52" searchable={false}
          data-testid="notif-filter-event">
          <option value="all">Semua jenis</option>
          {['stage_change', 'invoice_issued', 'invoice_overdue', 'manual'].map((e) => <option key={e} value={e}>{EVENT_LABEL[e]}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="notifikasi-klien" namaLembar="Notifikasi" baris={filtered} ambilSemua={ambilSemua}
          kolom={kolomUnduh} testId="notif-unduh" />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {summary && !providerAktif && (
          <Notice tone="warning" icon={WifiOff} title="Mode uji aktif"
            action={<Button size="sm" variant="outline" onClick={goConfig}><Settings />Atur penyedia</Button>}>
            Notifikasi dicatat tetapi belum dikirim sungguhan ke klien.
          </Notice>
        )}
        {summary && providerAktif && (
          <p className="text-sm text-muted-foreground">
            Penyedia aktif: {[summary.whatsapp_configured && 'WhatsApp (Fonnte)', summary.email_configured && 'Email (SMTP)'].filter(Boolean).join(' · ')}
          </p>
        )}
        {summary && summary.total > 0 && (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="notif-stats">
            <StatTile label="Semua notifikasi" value={summary.total}
              sub={`${summary.by_channel?.whatsapp ?? 0} WhatsApp · ${summary.by_channel?.email ?? 0} email`}
              hint="Seluruh outbox klien, tidak ikut penyaring." />
            <StatTile label="Menunggu kirim" value={summary.by_status?.queued ?? 0} accent="warning" hint="Seluruh outbox, tidak ikut penyaring." />
            <StatTile label="Terkirim" value={summary.by_status?.sent ?? 0} accent="success" hint="Seluruh outbox, tidak ikut penyaring." />
            <StatTile label="Gagal" value={summary.by_status?.failed ?? 0} accent="danger" hint="Seluruh outbox, tidak ikut penyaring." />
          </div>
        )}
      </>}
      footer={terpotong && (
        <p className="text-xs text-muted-foreground">Menampilkan 100 notifikasi terbaru. Unduh berisi semua yang cocok dengan saringan.</p>
      )}>
      {loading && items.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat notifikasi…</p>
      ) : (
        <TabelData kolom={kolom} baris={filtered} onKlikBaris={setDetail} testId="notif-list"
          kosong={<EmptyState title={adaSaring ? 'Tidak ada notifikasi yang cocok' : 'Belum ada notifikasi'}
            description={adaSaring ? 'Ubah saringan atau kata pencarian.' : 'Notifikasi ke klien muncul di sini saat tahap produksi berubah atau faktur terbit.'} />} />
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={`Notifikasi ke ${detail.recipient}`} testId="notif-detail"
          status={<StatusBadge status={detail.status} label={statusN(detail.status).label} tone={statusN(detail.status).tone} />}
          aksi={<>
            {detail.status === 'queued' && <Button size="sm" variant="outline" onClick={() => markSent(detail.id)}><Send />Kirim</Button>}
            {detail.status === 'failed' && <Button size="sm" variant="outline" onClick={() => retry(detail.id)}><RotateCw />Ulangi</Button>}
            <Button size="sm" variant="destructive" onClick={() => remove(detail.id)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Saluran">{CHANNEL_LABEL[detail.channel] || detail.channel}</BarisDetail>
            <BarisDetail label="Jenis">{labelEvent(detail.event_type)}</BarisDetail>
            {detail.subject && <BarisDetail label="Subjek">{detail.subject}</BarisDetail>}
            <BarisDetail label="Isi pesan"><span className="whitespace-pre-wrap">{detail.body}</span></BarisDetail>
            <BarisDetail label="Dibuat">{waktu(detail.created_at)}</BarisDetail>
            {detail.sent_at && <BarisDetail label="Dikirim">{waktu(detail.sent_at)}</BarisDetail>}
            <BarisDetail label="Cara kirim">{detail.sent_real ? 'Dikirim lewat penyedia sungguhan' : detail.sent_mock ? 'Mode uji (tidak dikirim sungguhan)' : '—'}</BarisDetail>
            {detail.error && <BarisDetail label="Galat"><span className="text-[hsl(var(--danger-text))]">{detail.error}</span></BarisDetail>}
          </dl>
        </DetailPopup>
      )}
    </PageLayout>
  );
}

// ─── TAB 2 · KONFIGURASI PENYEDIA ───────────────────────────────────────────
function FormKonfigurasi({ awal, headers, onClose, onTersimpan }) {
  const [cfg, setCfg] = useState(awal);
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');
  const save = async () => {
    setSaving(true);
    setGalat('');
    try {
      const r = await fetch('/api/dewi/notifications/provider-config', { method: 'PUT', headers, body: JSON.stringify(cfg) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal menyimpan konfigurasi.');
      toast.success('Konfigurasi penyedia disimpan.');
      onTersimpan();
      onClose();
    } catch (err) { setGalat(err.message); }
    finally { setSaving(false); }
  };
  const isian = (label, field, { type = 'text', placeholder = '', petunjuk } = {}) => (
    <Isian label={label} htmlFor={`cfg-${field}`} petunjuk={petunjuk}>
      <Input id={`cfg-${field}`} type={type} value={cfg[field] || ''} placeholder={placeholder}
        onChange={(e) => setCfg((p) => ({ ...p, [field]: e.target.value }))} />
    </Isian>
  );
  const sakelar = (label, field) => (
    <label className="flex items-center justify-between gap-3 text-sm" htmlFor={`cfg-${field}`}>
      <span>{label}</span>
      <Switch id={`cfg-${field}`} checked={!!cfg[field]} onCheckedChange={(v) => setCfg((p) => ({ ...p, [field]: v }))} />
    </label>
  );
  return (
    <FormPopup open onClose={onClose} judul="Ubah konfigurasi penyedia" ukuran="panjang" onSimpan={save} menyimpan={saving}
      galat={galat} labelSimpan="Simpan konfigurasi" testId="notif-config-form"
      keterangan="WhatsApp lewat Fonnte, email lewat SMTP. Kosongkan kata sandi bila tidak diganti.">
      <p className="text-base font-semibold">WhatsApp (Fonnte)</p>
      <p className="text-xs text-muted-foreground">Daftar di <a href="https://fonnte.com" target="_blank" rel="noreferrer" className="text-primary underline">fonnte.com</a> untuk mendapatkan kunci API WhatsApp Business.</p>
      {sakelar('Aktifkan WhatsApp', 'whatsapp_enabled')}
      {isian('Kunci API Fonnte', 'whatsapp_api_key', { type: 'password', placeholder: 'Masukkan kunci API' })}
      <div className="grid gap-4 sm:grid-cols-2">
        {isian('Kode negara', 'whatsapp_country_code', { placeholder: '62' })}
        {isian('Nomor uji', 'whatsapp_test_phone', { placeholder: '628xxxxxxxxx' })}
      </div>
      {isian('Nama pengirim', 'whatsapp_sender_name', { placeholder: 'CV. Dewi Aditya' })}

      <p className="border-t border-[var(--glass-border)] pt-4 text-base font-semibold">Email (SMTP)</p>
      <p className="text-xs text-muted-foreground">Pakai Gmail (smtp.gmail.com:587) atau penyedia SMTP lain. Untuk Gmail, aktifkan "Sandi aplikasi".</p>
      {sakelar('Aktifkan email', 'email_enabled')}
      <div className="grid gap-4 sm:grid-cols-2">
        {isian('Server SMTP', 'smtp_host', { placeholder: 'smtp.gmail.com' })}
        {isian('Port', 'smtp_port', { placeholder: '587' })}
      </div>
      {/* FASE 10 — mode keamanan eksplisit (relay internal tanpa TLS / tanpa login bisa dipakai). */}
      <Isian label="Keamanan koneksi" htmlFor="cfg-smtp_security"
        petunjuk="Nama pengguna & kata sandi boleh kosong bila server mengizinkan kirim tanpa login.">
        <SmartNativeSelect id="cfg-smtp_security" value={cfg.smtp_security || 'starttls'} searchable={false}
          onChange={(e) => setCfg((p) => ({ ...p, smtp_security: e.target.value }))} data-testid="smtp-security-select">
          <option value="starttls">STARTTLS — port 587 (umum: Gmail, Zoho, Outlook)</option>
          <option value="ssl">SSL/TLS — port 465</option>
          <option value="none">Tanpa enkripsi — relay/SMTP internal</option>
        </SmartNativeSelect>
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        {isian('Nama pengguna (email)', 'smtp_user', { placeholder: 'demo@gmail.com' })}
        {isian('Kata sandi / sandi aplikasi', 'smtp_password', { type: 'password', placeholder: '*****' })}
        {isian('Alamat pengirim', 'smtp_from_email', { placeholder: 'noreply@demo-erp.id' })}
        {isian('Nama pengirim', 'smtp_from_name', { placeholder: 'CV. Dewi Aditya' })}
      </div>
      {isian('Email uji', 'smtp_test_email', { placeholder: 'test@email.com' })}

      <p className="border-t border-[var(--glass-border)] pt-4 text-base font-semibold">Rapor valuasi aksesoris bulanan</p>
      <p className="text-xs text-muted-foreground">Setiap tanggal 1 pukul 06.00 WIB rapor valuasi aksesoris bulan lalu (Excel + PDF) dikirim ke semua pengguna keuangan. Penerima & riwayat ada di Aksesoris › Valuasi HPP.</p>
      {sakelar('Kirim rapor otomatis setiap awal bulan', 'valuation_report_enabled')}
      <Isian label="Email tambahan" htmlFor="cfg-val-extra" petunjuk="Pisahkan dengan koma.">
        <Input id="cfg-val-extra" data-testid="valuation-report-extra-emails" placeholder="pajak@perusahaan.id, arsip@perusahaan.id"
          value={Array.isArray(cfg.valuation_report_extra_emails) ? cfg.valuation_report_extra_emails.join(', ') : (cfg.valuation_report_extra_emails || '')}
          onChange={(e) => setCfg((p) => ({ ...p, valuation_report_extra_emails: e.target.value }))} />
      </Isian>

      <p className="border-t border-[var(--glass-border)] pt-4 text-base font-semibold">Notifikasi otomatis</p>
      {sakelar('Saat tahap maklon berubah', 'notify_on_stage_change')}
      {sakelar('Saat faktur diterbitkan', 'notify_on_invoice_issued')}
      {sakelar('Saat faktur lewat jatuh tempo', 'notify_on_invoice_overdue')}
      {sakelar('Saat sample diperbarui', 'notify_on_sample_update')}
    </FormPopup>
  );
}

function ProviderConfigTab({ headers }) {
  const [cfg, setCfg] = useState({});
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [form, setForm] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/dewi/notifications/provider-config', { headers });
      if (r.ok) setCfg(await r.json());
    } finally { setLoading(false); }
  }, [headers]);
  useEffect(() => { load(); }, [load]);

  const testSend = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await fetch('/api/dewi/notifications/provider-config/test', { method: 'POST', headers });
      const d = await r.json();
      setTestResult(d);
      if (d.whatsapp?.success || d.email?.success) toast.success('Uji kirim berhasil.');
      else toast.warning('Uji kirim gagal — lihat keterangan di halaman.');
    } catch (err) { toast.error(err.message); }
    finally { setTesting(false); }
  };

  const ada = (v) => (v ? 'Tersimpan' : 'Belum diisi');
  const bagian = (judul, baris, status) => (
    <GlassCard className="space-y-2 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="flex-1 text-base font-semibold text-foreground">{judul}</p>
        {status}
      </div>
      <dl className="divide-y divide-[var(--glass-border)]">
        {baris.map(([l, v]) => <BarisDetail key={l} label={l}>{v || '—'}</BarisDetail>)}
      </dl>
    </GlassCard>
  );
  const badge = (ok, ya2, tidak) => <StatusBadge status={ok ? 'ok' : 'belum'} label={ok ? ya2 : tidak} tone={ok ? 'success' : 'muted'} />;

  return (
    <PageLayout testId="notif-config-tab" title="Konfigurasi penyedia" subtitle="Penyedia WhatsApp & email untuk notifikasi klien."
      actions={<>
        <Button variant="outline" onClick={testSend} disabled={testing} data-testid="notif-config-test"><TestTube />{testing ? 'Menguji…' : 'Uji kirim'}</Button>
        <Button onClick={() => setForm(true)} disabled={loading} data-testid="notif-config-edit"><Settings />Ubah konfigurasi</Button>
      </>}>
      {loading ? <p className="py-6 text-center text-sm text-muted-foreground">Memuat konfigurasi…</p> : (
        <div className="grid gap-4 lg:grid-cols-2">
          {bagian('WhatsApp (Fonnte)', [
            ['Aktif', ya(cfg.whatsapp_enabled)], ['Kunci API', ada(cfg.whatsapp_api_key)],
            ['Kode negara', cfg.whatsapp_country_code], ['Nomor uji', cfg.whatsapp_test_phone], ['Nama pengirim', cfg.whatsapp_sender_name],
          ], badge(cfg.whatsapp_configured, 'Terkonfigurasi', 'Belum diatur'))}
          {bagian('Email (SMTP)', [
            ['Aktif', ya(cfg.email_enabled)], ['Server', cfg.smtp_host ? `${cfg.smtp_host}${cfg.smtp_port ? `:${cfg.smtp_port}` : ''}` : ''],
            ['Keamanan', { starttls: 'STARTTLS', ssl: 'SSL/TLS', none: 'Tanpa enkripsi' }[cfg.smtp_security || 'starttls']],
            ['Nama pengguna', cfg.smtp_user], ['Kata sandi', ada(cfg.smtp_password)],
            ['Pengirim', [cfg.smtp_from_name, cfg.smtp_from_email].filter(Boolean).join(' · ')], ['Email uji', cfg.smtp_test_email],
          ], badge(cfg.email_configured, 'Terkonfigurasi', 'Belum diatur'))}
          {bagian('Rapor valuasi aksesoris bulanan', [
            ['Kirim otomatis', ya(cfg.valuation_report_enabled)],
            ['Email tambahan', Array.isArray(cfg.valuation_report_extra_emails) ? cfg.valuation_report_extra_emails.join(', ') : cfg.valuation_report_extra_emails],
          ])}
          {bagian('Notifikasi otomatis', [
            ['Tahap maklon berubah', ya(cfg.notify_on_stage_change)], ['Faktur diterbitkan', ya(cfg.notify_on_invoice_issued)],
            ['Faktur lewat jatuh tempo', ya(cfg.notify_on_invoice_overdue)], ['Sample diperbarui', ya(cfg.notify_on_sample_update)],
          ])}
        </div>
      )}
      {testResult && (
        <div className="space-y-2">
          {['whatsapp', 'email'].map((ch) => (
            <Notice key={ch} tone={testResult[ch]?.success ? 'success' : 'danger'} icon={testResult[ch]?.success ? CheckCircle2 : XCircle}
              title={`${CHANNEL_LABEL[ch]}: ${testResult[ch]?.success ? 'berhasil' : 'gagal'}`}>
              {testResult[ch]?.error}
            </Notice>
          ))}
        </div>
      )}
      {form && <FormKonfigurasi awal={cfg} headers={headers} onClose={() => setForm(false)} onTersimpan={load} />}
    </PageLayout>
  );
}

// ─── TAB 3 · JOB TERJADWAL ──────────────────────────────────────────────────
function SchedulerTab({ headers, onRan }) {
  const [scheduler, setScheduler] = useState(null);
  const [runs, setRuns] = useState([]);
  const [runningJob, setRunningJob] = useState(null);
  const [memuat, setMemuat] = useState(false);

  const loadScheduler = useCallback(async () => {
    setMemuat(true);
    try {
      const [r1, r2] = await Promise.all([
        fetch('/api/dewi/scheduler/jobs', { headers }),
        fetch('/api/dewi/scheduler/runs?limit=20', { headers }),
      ]);
      if (r1.ok) setScheduler(await r1.json());
      if (r2.ok) setRuns(await r2.json());
    } catch {}
    finally { setMemuat(false); }
  }, [headers]);
  useEffect(() => { loadScheduler(); }, [loadScheduler]);

  const runJob = async (job) => {
    setRunningJob(job.id);
    try {
      const r = await fetch(`/api/dewi/scheduler/jobs/${job.id}/run-now`, { method: 'POST', headers });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal');
      toast.success(`Job selesai. ${d.result?.notifs_queued ?? 0} notifikasi baru.`);
      loadScheduler(); onRan?.();
    } catch (e) { toast.error(e.message); }
    finally { setRunningJob(null); }
  };

  const jobs = scheduler?.jobs || [];
  const peta = Object.fromEntries(jobs.map((j) => [j.id, j.description]));
  const namaJob = (id) => peta[id] || String(id || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
  const { page, setPage, totalPages, total, paged } = useClientPagination(runs, 10);
  const stRun = (s) => (s === 'success' ? { label: 'Berhasil', tone: 'success' } : s === 'failed' ? { label: 'Gagal', tone: 'danger' } : { label: 'Berjalan', tone: 'warning' });

  const kolomJob = [
    { kunci: 'job', label: 'Job', hp: 'judul', isi: (j) => <p className="line-clamp-2 md:max-w-[34rem]" title={j.description}>{j.description}</p> },
    { kunci: 'jadwal', label: 'Jadwal', isi: (j) => <span className="md:whitespace-nowrap">{j.cron_label}</span> },
    { kunci: 'status', label: 'Status', isi: (j) => <StatusBadge status={j.enabled ? 'aktif' : 'nonaktif'} label={j.enabled ? 'Aktif' : 'Nonaktif'} tone={j.enabled ? 'success' : 'muted'} /> },
    { kunci: 'berikut', label: 'Berikutnya', isi: (j) => <span className="tabular-nums md:whitespace-nowrap">{waktu(j.next_run_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (j) => (
      <Button size="sm" variant="outline" disabled={runningJob === j.id || !j.enabled} onClick={() => runJob(j)}>
        <PlayCircle />{runningJob === j.id ? 'Menjalankan…' : 'Jalankan sekarang'}
      </Button>) },
  ];
  const kolomRun = [
    { kunci: 'job', label: 'Job', hp: 'judul', isi: (r) => <p className="truncate md:max-w-[22rem]" title={namaJob(r.job_id)}>{namaJob(r.job_id)}</p> },
    { kunci: 'mulai', label: 'Mulai', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{waktu(r.started_at)}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusBadge status={r.status} label={stRun(r.status).label} tone={stRun(r.status).tone} /> },
    { kunci: 'durasi', label: 'Durasi (ms)', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.duration_ms ?? '—'}</span> },
    { kunci: 'periksa', label: 'Diperiksa', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.invoices_checked ?? '—'}</span> },
    { kunci: 'notif', label: 'Notifikasi', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.notifs_queued ?? '—'}</span> },
  ];

  return (
    <PageLayout testId="notif-scheduler-tab" title="Job terjadwal" subtitle="Job yang membuat notifikasi secara otomatis."
      tools={<>
        <TombolUnduh namaBerkas="job-terjadwal" namaLembar="Job" baris={jobs} label="Unduh job" testId="notif-job-unduh"
          kolom={[
            { label: 'Job', nilai: (j) => j.description },
            { label: 'Jadwal', nilai: (j) => j.cron_label },
            { label: 'Status', nilai: (j) => (j.enabled ? 'Aktif' : 'Nonaktif') },
            { label: 'Berikutnya', nilai: (j) => waktu(j.next_run_at) },
          ]} />
        <Button variant="outline" size="icon" onClick={loadScheduler} disabled={memuat} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={memuat ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={scheduler && (
        <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <StatusBadge status={scheduler.scheduler_running ? 'aktif' : 'nonaktif'}
            label={scheduler.scheduler_running ? 'Penjadwal berjalan' : 'Penjadwal berhenti'}
            tone={scheduler.scheduler_running ? 'success' : 'danger'} />
          {scheduler.timezone && <span>Zona waktu {scheduler.timezone === 'Asia/Jakarta' ? 'WIB' : scheduler.timezone}</span>}
        </p>
      )}>
      <TabelData kolom={kolomJob} baris={jobs} testId="notif-jobs-table"
        kosong={!memuat && <EmptyState title="Tidak ada job terdaftar" description="Job muncul setelah server menyalakan penjadwal." />} />
      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 text-base font-semibold text-foreground">Riwayat jalan · {runs.length} terakhir</p>
          <TombolUnduh namaBerkas="riwayat-job" namaLembar="Riwayat" baris={runs} testId="notif-run-unduh"
            kolom={[
              { label: 'Job', nilai: (r) => namaJob(r.job_id) },
              { label: 'Mulai', nilai: (r) => waktu(r.started_at) },
              { label: 'Status', nilai: (r) => stRun(r.status).label },
              { label: 'Durasi (ms)', nilai: (r) => r.duration_ms ?? '' },
              { label: 'Diperiksa', nilai: (r) => r.invoices_checked ?? '' },
              { label: 'Notifikasi', nilai: (r) => r.notifs_queued ?? '' },
            ]} />
        </div>
        <TabelData kolom={kolomRun} baris={paged} kunci={(r) => `${r.job_id}-${r.started_at}`} testId="notif-runs-table"
          kosong={!memuat && <EmptyState title="Belum ada riwayat jalan" description="Riwayat muncul setelah job pertama berjalan." />} />
        {runs.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}
      </section>
    </PageLayout>
  );
}

// ─── MODUL ──────────────────────────────────────────────────────────────────
export default function NotificationCenterModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [summary, setSummary] = useState(null);
  const [tab, setTab] = useState('notifications');

  const loadSummary = useCallback(async () => {
    try {
      const r2 = await fetch('/api/dewi/notifications/summary', { headers });
      if (r2.ok) setSummary(await r2.json());
    } catch {}
  }, [headers]);

  return (
    <div data-testid="notification-center">
      <HubTabs hubId="notification-center-tabs" title="Notifikasi"
        subtitle="Pesan otomatis ke klien (WhatsApp & email), penyedia pengirim, dan job terjadwal."
        value={tab} onValueChange={setTab}
        tabs={[
          { key: 'notifications', label: 'Notifikasi', Component: NotifListTab,
            props: { headers, summary, onChanged: loadSummary, goConfig: () => setTab('config') } },
          { key: 'config', label: 'Penyedia pengirim', Component: ProviderConfigTab, props: { headers } },
          { key: 'scheduler', label: 'Job terjadwal', Component: SchedulerTab, props: { headers, onRan: loadSummary } },
        ]} />
    </div>
  );
}

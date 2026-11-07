/**
 * Input Sales (Portal Marketing) — rekap penjualan harian per akun (total & live).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, pemilih akun aktif + penyaring satu baris, tabel standar +
 * unduh Excel/CSV, form = FormPopup panjang dengan pemilih tanggal seragam (dulu input tanggal bawaan peramban),
 * jenis omzet = pilihan (dulu tab beremoji), bahasa Indonesia.
 * Perbaikan: daftar dulu hanya memuat 10 toko pertama tanpa keterangan — kini semua toko.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Plus, RefreshCw, Loader2, Calendar, Lock, Calculator, ShieldAlert } from 'lucide-react';
import { useActiveMarketingAccount } from '@/hooks/useActiveMarketingAccount';
import { ActiveAccountBar } from './marketing/ActiveAccountBar';
import { MoneyInput } from '@/components/ui/money-input';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker, { formatTanggalID, hariIniWIB } from '@/components/ui/date-picker';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import { toast } from 'sonner';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah } from '@/lib/format';
import { todayWIB, daysAgoWIB } from '@/lib/waktu';

const fmt = formatRupiah;
const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID');
const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok', tiktokshop: 'TikTok', tokopedia: 'Tokopedia', lazada: 'Lazada' };
const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '—';

function SalesDataEntryDialog({ open, onOpenChange, onSaved, token, accounts, preSelectedAccountId }) {
  const [submitting, setSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState('total');
  // F2 (2026-08-12) — JALAN KELUAR SPV. Backend sudah punya jalur
  // `POST /sales-data?override=true&override_reason=…` sejak F2, tetapi TIDAK ADA
  // satu pun layar yang memanggilnya: staf hanya melihat penolakan 409 dan
  // kebuntuan. Tiga state di bawah membuat kuncinya bisa dijelaskan DAN dibuka
  // oleh yang berwenang, dengan alasan yang tercatat.
  const [existingRow, setExistingRow] = useState(null);   // baris rekap yang sudah ada
  const [checkingLock, setCheckingLock] = useState(false);
  const [overrideMode, setOverrideMode] = useState(false);
  const [overrideReason, setOverrideReason] = useState('');
  const [saveError, setSaveError] = useState('');          // pesan galat yang MENETAP
  const [form, setForm] = useState({
    account_id: '',
    date: todayWIB(),
    revenue: '',
    orders: '',
    aov: '',
    gmv: '',
    conversion_rate: '',
    fulfillment_rate: '',
    cancellation_rate: '',
    return_rate: '',
    late_shipment_rate: '',
    rating: '',
    review_count: '',
    response_rate: '',
    response_time_hours: '',
    // live-only
    viewers: '',
    avg_viewers: '',
    likes: '',
    shares: '',
    comments: '',
    new_followers: '',
    live_sessions: '',
  });

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  useEffect(() => {
    if (!open) {
      // reset form on close
      setActiveTab('total');
      setForm({
        account_id: preSelectedAccountId || '',
        date: todayWIB(),
        revenue: '',
        orders: '',
        aov: '',
        gmv: '',
        conversion_rate: '',
        fulfillment_rate: '',
        cancellation_rate: '',
        return_rate: '',
        late_shipment_rate: '',
        rating: '',
        review_count: '',
        response_rate: '',
        response_time_hours: '',
        viewers: '',
        avg_viewers: '',
        likes: '',
        shares: '',
        comments: '',
        new_followers: '',
        live_sessions: '',
      });
    } else if (open && preSelectedAccountId) {
      setForm(f => ({ ...f, account_id: preSelectedAccountId }));
    }
  }, [open, preSelectedAccountId]);

  const num = (v) => v === '' || v === null ? null : parseFloat(v);

  /* ── F2 — apakah (toko, tanggal, tipe) ini angkanya TURUNAN? ──────────────
     Diperiksa SEBELUM tombol simpan ditekan supaya staf tahu kuncinya lebih
     dulu, bukan setelah formnya diisi penuh lalu ditolak 409.                */
  useEffect(() => {
    if (!open || !form.account_id || !form.date) { setExistingRow(null); return; }
    let alive = true;
    (async () => {
      setCheckingLock(true);
      try {
        const qs = new URLSearchParams({
          date_from: form.date, date_to: form.date, revenue_type: activeTab,
        });
        const r = await fetch(
          `/api/marketing/accounts/${form.account_id}/sales?${qs.toString()}`, { headers });
        const list = r.ok ? await r.json().catch(() => []) : [];
        if (alive) setExistingRow(Array.isArray(list) && list.length ? list[0] : null);
      } catch (e) {
        if (alive) setExistingRow(null);
      } finally {
        if (alive) setCheckingLock(false);
      }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, form.account_id, form.date, activeTab]);

  const derivedRow = !!existingRow
    && (existingRow.locked_source === true || existingRow.source === 'orders_auto');
  const lockedMetrics = derivedRow && !overrideMode;
  const existingMetrics = existingRow?.metrics || {};

  useEffect(() => {
    // ganti tanggal / toko / tipe ⇒ mode override & galat lama tidak boleh menempel
    setOverrideMode(false);
    setOverrideReason('');
    setSaveError('');
  }, [form.account_id, form.date, activeTab]);

  const handleSubmit = async () => {
    setSaveError('');
    if (!form.account_id) {
      setSaveError('Pilih akun terlebih dahulu.');
      return;
    }
    if (!form.date) {
      setSaveError('Tanggal wajib diisi.');
      return;
    }
    if (overrideMode && overrideReason.trim().length < 5) {
      setSaveError('Alasan penggantian wajib diisi (minimal 5 huruf) — inilah yang '
        + 'membuat perubahan angka bisa dipertanggungjawabkan.');
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        account_id: form.account_id,
        date: form.date,
        revenue_type: activeTab,
        revenue: num(form.revenue) || 0,
        orders: num(form.orders) || 0,
        aov: num(form.aov),
        gmv: num(form.gmv),
        conversion_rate: num(form.conversion_rate),
        fulfillment_rate: num(form.fulfillment_rate),
        cancellation_rate: num(form.cancellation_rate),
        return_rate: num(form.return_rate),
        late_shipment_rate: num(form.late_shipment_rate),
        rating: num(form.rating),
        review_count: num(form.review_count),
        response_rate: num(form.response_rate),
        response_time_hours: num(form.response_time_hours),
      };

      if (activeTab === 'live') {
        payload.viewers = num(form.viewers);
        payload.avg_viewers = num(form.avg_viewers);
        payload.likes = num(form.likes);
        payload.shares = num(form.shares);
        payload.comments = num(form.comments);
        payload.new_followers = num(form.new_followers);
        payload.live_sessions = num(form.live_sessions);
      }

      const url = overrideMode
        ? `/api/marketing/sales-data?override=true&override_reason=${encodeURIComponent(overrideReason.trim())}`
        : '/api/marketing/sales-data';
      const res = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const detail = err.detail || `Gagal menyimpan data (HTTP ${res.status})`;
        const e2 = new Error(detail);
        e2.status = res.status;
        throw e2;
      }

      toast.success(overrideMode
        ? 'Angka diganti (penggantian SPV) dan alasannya dicatat'
        : `Data omzet ${activeTab === 'total' ? 'total' : 'live'} tersimpan`);
      setOverrideMode(false);
      setOverrideReason('');
      onOpenChange(false);
      if (onSaved) onSaved();
    } catch (err) {
      // Pesan 409/403/400 dari F2 panjang dan berisi JALAN KELUAR — kalau hanya
      // lewat toast 4 detik, staf tidak pernah selesai membacanya. Karena itu
      // pesan yang sama juga DITAHAN di dalam form sampai datanya diubah.
      setSaveError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const accSel = accounts?.find(a => a.id === form.account_id);
  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} ukuran="panjang" onSimpan={handleSubmit}
      menyimpan={submitting} galat={saveError ? <span data-testid="sd-save-error">{saveError}</span> : null}
      labelSimpan={overrideMode ? 'Simpan penggantian' : 'Simpan'} testId="sales-data-dialog"
      judul="Input sales harian"
      keterangan="Pilih akun, tanggal, dan jenis omzet, lalu isi angkanya. Skor kesehatan toko dihitung ulang otomatis.">
      <div className="grid gap-4 sm:grid-cols-3">
        <Isian label="Akun" wajib petunjuk={accSel ? `Input ke: ${accSel.account_name}` : undefined}>
          <SmartNativeSelect className="w-full" value={form.account_id} onChange={e => setForm(f => ({ ...f, account_id: e.target.value }))}
            data-testid="sd-account-select">
            <option value="">Pilih akun…</option>
            {accounts?.map(a => <option key={a.id} value={a.id}>{a.account_name} ({labelPlatform(a.platform)})</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Tanggal" wajib>
          <DatePicker value={form.date} onChange={(v) => setForm(f => ({ ...f, date: v }))} bolehKosong={false}
            max={hariIniWIB()} testId="sd-date-input" />
        </Isian>
        <Isian label="Jenis omzet" wajib petunjuk={activeTab === 'live' ? 'Khusus penjualan dari live streaming.' : 'Total penjualan semua kanal (reguler + live).'}>
          <SmartNativeSelect className="w-full" value={activeTab} onChange={(e) => setActiveTab(e.target.value)} data-testid="sd-type-select">
            <option value="total">Total (semua kanal)</option>
            <option value="live">Live</option>
          </SmartNativeSelect>
        </Isian>
      </div>

      {/* F2 — KUNCI ANGKA TURUNAN + jalan keluar SPV */}
      {checkingLock && (
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Memeriksa sumber angka tanggal ini…
        </p>
      )}
      {derivedRow && (
        <Notice tone="warning" icon={Lock} testId="sd-locked-notice"
          title={`Angka ${formatTanggalID(form.date)} diturunkan dari pesanan toko ini`}>
          <p>
            Omzet <b>{fmt(existingMetrics.revenue)}</b> dari <b>{fmtNum(existingMetrics.orders)} pesanan</b>. Kolom omzet dan
            jumlah pesanan dikunci supaya tidak ada dua angka omzet untuk satu hari. Kalau salah, perbaiki pesanannya
            (Impor Data / Order Terpadu) — bukan diketik ulang di sini.
          </p>
          {!overrideMode ? (
            <Button type="button" size="sm" variant="outline" className="mt-2"
              onClick={() => {
                // Angka turunan dipakai sebagai TITIK AWAL: SPV hampir selalu hanya mengoreksi sebagian.
                setForm(f => ({
                  ...f,
                  revenue: f.revenue || String(existingMetrics.revenue ?? ''),
                  orders: f.orders || String(existingMetrics.orders ?? ''),
                }));
                setOverrideMode(true);
              }} data-testid="sd-override-btn">
              <ShieldAlert />Ganti angka (penggantian SPV)
            </Button>
          ) : (
            <div className="mt-2 space-y-2">
              <Isian label="Alasan penggantian" wajib htmlFor="sd-override-reason"
                petunjuk="Tercatat beserta nama & waktu; angka hasil penggantian tidak ditimpa perhitungan otomatis berikutnya.">
                <Textarea id="sd-override-reason" value={overrideReason} onChange={(e) => setOverrideReason(e.target.value)} rows={2}
                  placeholder="Contoh: ekspor Seller Center hari itu belum lengkap, angka dari dashboard platform"
                  data-testid="sd-override-reason" />
              </Isian>
              <Button type="button" size="sm" variant="ghost"
                onClick={() => { setOverrideMode(false); setOverrideReason(''); }} data-testid="sd-override-cancel">
                Batalkan penggantian
              </Button>
            </div>
          )}
        </Notice>
      )}

      <CommonMetricsForm form={form} setForm={setForm} lockedMetrics={lockedMetrics} />

      {activeTab === 'live' && (
        <>
          <p className="border-t border-[var(--glass-border)] pt-4 text-sm font-semibold">Keterlibatan penonton (khusus live)</p>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <NumField label="Penonton" testId="sd-viewers" value={form.viewers} onChange={v => setForm(f => ({ ...f, viewers: v }))} />
            <NumField label="Rata-rata penonton" testId="sd-avg-viewers" value={form.avg_viewers} onChange={v => setForm(f => ({ ...f, avg_viewers: v }))} />
            <NumField label="Suka" testId="sd-likes" value={form.likes} onChange={v => setForm(f => ({ ...f, likes: v }))} />
            <NumField label="Dibagikan" testId="sd-shares" value={form.shares} onChange={v => setForm(f => ({ ...f, shares: v }))} />
            <NumField label="Komentar" testId="sd-comments" value={form.comments} onChange={v => setForm(f => ({ ...f, comments: v }))} />
            <NumField label="Pengikut baru" testId="sd-followers" value={form.new_followers} onChange={v => setForm(f => ({ ...f, new_followers: v }))} />
            <NumField label="Sesi live" testId="sd-sessions" value={form.live_sessions} onChange={v => setForm(f => ({ ...f, live_sessions: v }))} />
          </div>
        </>
      )}
    </FormPopup>
  );
}

// `money` = kolom nominal Rupiah (omzet/AOV/GMV) → MoneyInput (titik ribuan otomatis, No.45).
function NumField({ label, value, onChange, testId, step = '0.01', disabled = false, hint, money = false }) {
  const Field = money ? MoneyInput : Input;
  return (
    <Isian label={<span className="inline-flex items-center gap-1">{label}{disabled && <Lock size={12} className="text-[hsl(var(--warning-text))]" />}</span>}
      petunjuk={disabled && hint ? hint : undefined}>
      <Field
        type={money ? undefined : 'number'}
        step={money ? undefined : step}
        value={value}
        onChange={e => onChange(e.target.value)}
        disabled={disabled}
        readOnly={disabled}
        className={disabled ? 'cursor-not-allowed opacity-60' : undefined}
        data-testid={testId}
      />
    </Isian>
  );
}

function CommonMetricsForm({ form, setForm, lockedMetrics = false }) {
  // F2 — hanya omzet & jumlah pesanan yang DITURUNKAN dari pesanan; sisanya tetap boleh diisi manusia.
  const lockHint = 'Diturunkan dari pesanan';
  const [lanjutan, setLanjutan] = useState(false);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
        <NumField money label="Omzet (Rp)" testId="sd-revenue" value={form.revenue} onChange={v => setForm(f => ({ ...f, revenue: v }))} disabled={lockedMetrics} hint={lockHint} />
        <NumField label="Jumlah pesanan" testId="sd-orders" value={form.orders} onChange={v => setForm(f => ({ ...f, orders: v }))} disabled={lockedMetrics} hint={lockHint} />
        <NumField money label="Rata-rata per pesanan (AOV)" testId="sd-aov" value={form.aov} onChange={v => setForm(f => ({ ...f, aov: v }))} />
        <NumField money label="GMV" testId="sd-gmv" value={form.gmv} onChange={v => setForm(f => ({ ...f, gmv: v }))} />
        <NumField label="Konversi (%)" testId="sd-cr" value={form.conversion_rate} onChange={v => setForm(f => ({ ...f, conversion_rate: v }))} />
      </div>
      <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => setLanjutan(v => !v)}
        aria-expanded={lanjutan} data-testid="sd-advanced-toggle">
        {lanjutan ? 'Sembunyikan' : 'Tampilkan'} pengiriman & kepuasan pembeli (opsional)
      </Button>
      {lanjutan && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          <NumField label="Terpenuhi (%)" testId="sd-fr" value={form.fulfillment_rate} onChange={v => setForm(f => ({ ...f, fulfillment_rate: v }))} />
          <NumField label="Batal (%)" testId="sd-canc" value={form.cancellation_rate} onChange={v => setForm(f => ({ ...f, cancellation_rate: v }))} />
          <NumField label="Retur (%)" testId="sd-ret" value={form.return_rate} onChange={v => setForm(f => ({ ...f, return_rate: v }))} />
          <NumField label="Telat kirim (%)" testId="sd-late" value={form.late_shipment_rate} onChange={v => setForm(f => ({ ...f, late_shipment_rate: v }))} />
          <NumField label="Rating (0–5)" testId="sd-rating" value={form.rating} onChange={v => setForm(f => ({ ...f, rating: v }))} />
          <NumField label="Jumlah ulasan" testId="sd-review-count" value={form.review_count} onChange={v => setForm(f => ({ ...f, review_count: v }))} />
          <NumField label="Tingkat respons (%)" testId="sd-resp-rate" value={form.response_rate} onChange={v => setForm(f => ({ ...f, response_rate: v }))} />
          <NumField label="Waktu respons (jam)" testId="sd-resp-time" value={form.response_time_hours} onChange={v => setForm(f => ({ ...f, response_time_hours: v }))} />
        </div>
      )}
    </div>
  );
}


/**
 * F2 — dari mana angka baris ini datang. Ini yang mencegah "dua dunia omzet":
 * baris turunan TIDAK boleh diketik ulang; kalau salah, perbaiki pesanannya.
 */
const SOURCE_META = {
  orders_auto:     { label: 'Turunan dari pesanan', tone: 'success' },
  manual_override: { label: 'Diganti SPV',          tone: 'warning' },
  manual:          { label: 'Manual',               tone: 'info' },
  import:          { label: 'Impor rekap',          tone: 'info' },
  import_kpi:      { label: 'Impor KPI',            tone: 'info' },
  livehost_creator_auto: { label: 'Live otomatis',  tone: 'primary' },
  task_action:     { label: 'Dari tugas',           tone: 'muted' },
};
const sumberLabel = (row) => (SOURCE_META[row.source] || { label: row.source ? 'Lainnya' : 'Manual' }).label;

function SourceBadge({ row }) {
  const meta = SOURCE_META[row.source] || { label: row.source ? 'Lainnya' : 'Manual', tone: 'muted' };
  const locked = row.locked_source === true;
  return (
    <div className="min-w-0" data-testid={`sd-source-${row.id || ''}`}>
      <StatusBadge status={row.source} label={meta.label} tone={meta.tone} />
      {locked && <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground"><Lock size={12} />Tidak bisa diketik</p>}
      {row.override_reason && (
        <p className="mt-0.5 max-w-[12rem] truncate text-xs text-[hsl(var(--warning-text))]"
          title={`${row.override_reason} — oleh ${row.override_by || '-'}`}>Alasan: {row.override_reason}</p>
      )}
    </div>
  );
}

export default function SalesDataEntryModule({ token }) {
  const { activeAccount, setActiveAccount } = useActiveMarketingAccount();
  const [accounts, setAccounts] = useState([]);
  const [salesData, setSalesData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState({ account_id: 'all', revenue_type: 'all' });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [recomputing, setRecomputing] = useState(false);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const accRes = await fetch('/api/marketing/accounts', { headers });
      const accs = accRes.ok ? await accRes.json() : [];
      setAccounts(accs);

      // Data sales per toko (semua toko — dulu dipotong 10 toko pertama tanpa keterangan)
      const targetAccs = filter.account_id === 'all' ? accs : accs.filter(a => a.id === filter.account_id);
      const allSales = [];
      for (const acc of targetAccs) {
        const params = new URLSearchParams();
        if (filter.revenue_type !== 'all') params.append('revenue_type', filter.revenue_type);
        const r = await fetch(`/api/marketing/accounts/${acc.id}/sales?${params.toString()}`, { headers });
        if (r.ok) {
          const list = await r.json();
          list.forEach(item => {
            allSales.push({ ...item, _account_name: acc.account_name, _platform: acc.platform });
          });
        }
      }
      // urut tanggal terbaru dulu
      allSales.sort((a, b) => (b.date || '').localeCompare(a.date || ''));
      setSalesData(allSales);
    } catch (e) {
      toast.error('Gagal memuat data sales');
    } finally {
      setLoading(false);
    }
  }, [filter, headers]);

  /** F2 — hitung ulang rekap harian dari pesanan (60 hari terakhir) untuk toko terpilih. */
  const recompute = async (force = false) => {
    if (filter.account_id === 'all') {
      toast.info('Pilih satu toko dulu — hitung ulang dilakukan per toko');
      return;
    }
    setRecomputing(true);
    try {
      const res = await fetch(
        `/api/marketing/sales/recompute?account_id=${filter.account_id}`
        + `&date_from=${daysAgoWIB(60)}&date_to=${todayWIB()}&force=${force}`,
        { method: 'POST', headers });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || 'Gagal menghitung ulang');
      toast.success(body.message || 'Rekap harian dihitung ulang', { duration: 7000 });
      fetchData();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setRecomputing(false);
    }
  };

  useEffect(() => { fetchData(); }, [fetchData]);

  const { page, setPage, totalPages, total, paged } = useClientPagination(salesData, 25);
  const jenis = (t) => (t === 'live' ? 'Live' : t === 'total' ? 'Total' : (t || '—'));
  const kolom = [
    { kunci: 'tgl', label: 'Tanggal', isi: (row) => <span className="md:whitespace-nowrap">{formatTanggalID(row.date) || row.date}</span> },
    { kunci: 'akun', label: 'Akun', hp: 'judul', isi: (row) => (
      <div><p className="font-medium">{row._account_name}</p><p className="text-xs text-muted-foreground">{labelPlatform(row._platform)}</p></div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (row) => <StatusBadge status={row.revenue_type} label={jenis(row.revenue_type)} tone={row.revenue_type === 'live' ? 'primary' : 'default'} /> },
    { kunci: 'sumber', label: 'Sumber angka', isi: (row) => <SourceBadge row={row} /> },
    { kunci: 'omzet', label: 'Omzet', rata: 'kanan', isi: (row) => <span className="tabular-nums md:whitespace-nowrap">{fmt(row.metrics?.revenue)}</span> },
    { kunci: 'order', label: 'Pesanan', rata: 'kanan', isi: (row) => <span className="tabular-nums">{fmtNum(row.metrics?.orders)}</span> },
    { kunci: 'aov', label: 'AOV', rata: 'kanan', isi: (row) => <span className="tabular-nums md:whitespace-nowrap">{fmt(row.metrics?.aov)}</span> },
    // F0: satuan kanonik = PERSEN 0–100, jadi TIDAK dikali 100 lagi
    { kunci: 'cr', label: 'Konversi', rata: 'kanan', isi: (row) => <span className="tabular-nums">{row.metrics?.conversion_rate ? `${Number(row.metrics.conversion_rate).toLocaleString('id-ID', { maximumFractionDigits: 2 })}%` : '—'}</span> },
  ];

  return (
    <PageLayout testId="sales-data-entry-module" title="Input sales"
      subtitle="Penjualan harian (reguler dan live) per akun marketplace, dari pesanan atau diisi manual."
      actions={<>
        <Button onClick={() => recompute(false)} variant="outline" disabled={recomputing} data-testid="recompute-sales-btn"
          title={filter.account_id === 'all' ? 'Pilih satu toko dulu' : 'Hitung ulang 60 hari terakhir dari pesanan'}>
          {recomputing ? <Loader2 className="animate-spin" /> : <Calculator />}Hitung ulang dari pesanan
        </Button>
        <Button onClick={() => setDialogOpen(true)} data-testid="input-sales-btn"><Plus />Input sales</Button>
      </>}
      filters={<>
        <ActiveAccountBar
          accounts={accounts}
          activeAccount={activeAccount}
          onAccountChange={(acc) => {
            setActiveAccount(acc);
            setFilter(f => ({ ...f, account_id: acc ? acc.id : 'all' }));
          }}
          hint="Saring & isian otomatis ke akun"
        />
        <SmartNativeSelect className="w-48" value={filter.account_id} data-testid="sd-filter-account"
          onChange={e => setFilter(f => ({ ...f, account_id: e.target.value }))}>
          <option value="all">Semua akun</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect className="w-40" value={filter.revenue_type} data-testid="sd-filter-type"
          onChange={e => setFilter(f => ({ ...f, revenue_type: e.target.value }))}>
          <option value="all">Semua jenis</option>
          <option value="total">Total</option>
          <option value="live">Live</option>
        </SmartNativeSelect>
        <span className="text-sm text-muted-foreground">{fmtNum(salesData.length)} baris</span>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="input-sales-harian" namaLembar="Sales harian" baris={salesData} testId="sales-export-csv"
          kolom={[
            { label: 'Tanggal', nilai: (r) => formatTanggalID(r.date) || r.date }, { label: 'Akun', nilai: (r) => r._account_name },
            { label: 'Platform', nilai: (r) => labelPlatform(r._platform) }, { label: 'Jenis', nilai: (r) => jenis(r.revenue_type) },
            { label: 'Sumber angka', nilai: sumberLabel },
            { label: 'Omzet', nilai: (r) => r.metrics?.revenue ?? '' }, { label: 'Pesanan', nilai: (r) => r.metrics?.orders ?? '' },
            { label: 'AOV', nilai: (r) => r.metrics?.aov ?? '' }, { label: 'Konversi (%)', nilai: (r) => r.metrics?.conversion_rate ?? '' },
            { label: 'Alasan penggantian', nilai: (r) => r.override_reason || '' },
          ]} />
        <Button onClick={fetchData} variant="outline" size="icon" disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="refresh-sales-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      footer={salesData.length > 0 && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={25} onPageChange={setPage} />}>
      {loading && salesData.length === 0 ? (
        <div className="space-y-2">{[1, 2, 3, 4, 5].map(i => <Skeleton key={i} className="h-12" />)}</div>
      ) : (
        <TabelData kolom={kolom} baris={paged} kunci={(r) => r.id || `${r.account_id}-${r.date}-${r.revenue_type}`} testId="sales-table"
          kosong={<EmptyState icon={Calendar} title="Belum ada data sales"
            description="Data harian muncul dari pesanan yang diimpor, atau diisi manual."
            action={<Button onClick={() => setDialogOpen(true)} data-testid="input-first-sales-btn"><Plus />Input sales pertama</Button>} />} />
      )}

      <SalesDataEntryDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        accounts={accounts}
        onSaved={fetchData}
        token={token}
        preSelectedAccountId={activeAccount?.id || ''}
      />
    </PageLayout>
  );
}

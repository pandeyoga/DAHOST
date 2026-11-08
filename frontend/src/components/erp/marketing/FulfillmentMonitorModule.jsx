/**
 * FulfillmentMonitorModule — MONITORING PENGIRIMAN (F3).
 *
 * KENAPA LAYAR INI ADA
 * --------------------
 * Ekspor "Untuk Dikirim" memberi tahu pesanan mana yang menunggu, tetapi daftar
 * 559 baris tidak memberi tahu apa pun tentang PRIORITAS. Yang dibutuhkan tim
 * setiap pagi cuma tiga angka: berapa yang belum dikirim, berapa yang sudah
 * LEWAT BATAS (ini yang berubah menjadi penalti platform & pembatalan otomatis),
 * dan berapa yang batal.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris (kategori = pil), 4 kartu StatTile
 * ("Menunggu terlama" = "—" bila tidak ada yang menunggu, dulu "0.0 hari"), tabel standar + unduh Excel/CSV semua
 * halaman, form batas kirim = FormPopup.
 *
 * Batas kirim TIDAK dikarang di kode: ia tersimpan per toko dan bisa diubah dari
 * layar ini (tombol "Batas kirim"). Layar selalu menyebut batas yang dipakai —
 * daftar "merah" tanpa aturan yang bisa ditunjuk akan diabaikan staf.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, Info, Settings2, PackageCheck, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import PaginationLite from '@/components/ui/pagination-lite';
import { formatDateID } from '@/lib/format';
import { parseServerTime } from '@/lib/waktu';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL || '';
const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
const num = (n) => Number(n || 0).toLocaleString('id-ID');

const BUCKETS = [
  { key: 'lewat_batas', label: 'Lewat batas kirim' },
  { key: 'belum_dikirim', label: 'Belum dikirim' },
  { key: 'batal', label: 'Batal' },
  { key: 'retur', label: 'Retur' },
];
const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok', tiktokshop: 'TikTok', tokopedia: 'Tokopedia', lazada: 'Lazada' };
const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '—';
const tgl = (v) => (v ? formatDateID(parseServerTime(v)) : '—');

function SlaDialog({ open, onOpenChange, store, token, onSaved }) {
  const [normal, setNormal] = useState('2');
  const [pre, setPre] = useState('7');
  const [busy, setBusy] = useState(false);
  // Penolakan backend (mis. "pre-order tidak boleh lebih pendek…") DITAHAN di dalam
  // dialog. Uji layar 2026-08-12: dengan toast saja, penolakan itu tidak terlihat —
  // dialog tetap terbuka tanpa satu pun keterangan, jadi tampak seperti tombol
  // Simpan yang tidak berfungsi dan staf akan menekannya berulang kali.
  const [err, setErr] = useState('');

  useEffect(() => {
    if (open && store) {
      setNormal(String(store.sla_days ?? 2));
      setPre(String(store.sla_days_preorder ?? 7));
      setErr('');
    }
  }, [open, store]);

  const nNormal = parseFloat(normal);
  const nPre = parseFloat(pre);
  const localInvalid = !Number.isFinite(nNormal) || !Number.isFinite(nPre)
    || nNormal < 0.25 || nPre < 0.25 || nPre < nNormal;

  const save = async () => {
    setErr('');
    if (localInvalid) {
      setErr(!Number.isFinite(nNormal) || !Number.isFinite(nPre)
        ? 'Kedua batas harus berupa angka hari (minimal 0,25 hari = 6 jam).'
        : (nPre < nNormal
          ? `Batas pra-pesan (${nPre} hari) tidak boleh lebih pendek daripada batas pesanan `
            + `normal (${nNormal} hari) — pre-order justru butuh waktu lebih panjang.`
          : 'Batas minimal 0,25 hari (6 jam).'));
      return;
    }
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/marketing/accounts/${store.account_id}/ship-sla`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ship_sla_days: nNormal,
          ship_sla_days_preorder: nPre,
        }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        const detail = typeof body.detail === 'string' ? body.detail
          : (Array.isArray(body.detail) ? body.detail.map((d) => d.msg || '').join(' · ')
            : 'Gagal menyimpan batas kirim');
        throw new Error(detail);
      }
      toast.success(body.message || 'Batas kirim disimpan', { duration: 7000 });
      onOpenChange(false);
      onSaved?.();
    } catch (e) {
      setErr(e.message);
    } finally { setBusy(false); }
  };

  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} ukuran="pendek" onSimpan={save} menyimpan={busy}
      galat={err ? <span data-testid="sla-error">{err}</span> : null} judul={`Batas kirim — ${store?.account_name || ''}`}
      keterangan="Pesanan yang melewati batas ini dihitung lewat batas. Tiap platform punya tenggat berbeda, jadi batasnya disimpan per toko."
      testId="sla-dialog">
      <div className="grid grid-cols-2 gap-4">
        <Isian label="Pesanan normal (hari)" htmlFor="sla-normal">
          <Input id="sla-normal" type="number" step="0.5" min="0.25" value={normal}
            onChange={(e) => { setNormal(e.target.value); setErr(''); }} data-testid="sla-normal" />
        </Isian>
        <Isian label="Pra-pesan (hari)" htmlFor="sla-preorder">
          <Input id="sla-preorder" type="number" step="0.5" min="0.25" value={pre}
            onChange={(e) => { setPre(e.target.value); setErr(''); }} data-testid="sla-preorder" />
        </Isian>
      </div>
      <p className="text-xs text-muted-foreground">Batas pra-pesan tidak boleh lebih pendek daripada pesanan normal.</p>
    </FormPopup>
  );
}

export default function FulfillmentMonitorModule({ token }) {
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState('');
  const [bucket, setBucket] = useState('lewat_batas');
  // F10 — kebutuhan harian yang paling sering: "pesanan NOMOR ini kenapa belum
  // terkirim?". Tanpa pencarian, staf menggulir 500 baris.
  const [q, setQ] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [slaStore, setSlaStore] = useState(null);

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);

  const selectedAccount = useMemo(
    () => accounts.find((a) => a.id === accountId) || null, [accounts, accountId]);

  const loadAccounts = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/marketing/accounts?status=active`, { headers });
      const b = await r.json().catch(() => ({}));
      setAccounts(Array.isArray(b) ? b : (b.accounts || b.data || []));
    } catch { setAccounts([]); }
  }, [headers]);

  useEffect(() => { loadAccounts(); }, [loadAccounts]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ bucket, page: String(page), page_size: '50' });
      if (accountId) qs.set('account_id', accountId);
      const r = await fetch(`${API}/api/marketing/orders/fulfillment-monitor?${qs}`, { headers });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.detail || 'Gagal memuat monitoring pengiriman');
      setData(b);
    } catch (e) {
      toast.error(e.message, { duration: 9000 });
      setData(null);
    } finally { setLoading(false); }
  }, [headers, accountId, bucket, page]);

  useEffect(() => { load(); }, [load]);

  const t = data?.totals || {};
  const allRows = data?.rows || [];
  const needle = q.trim().toLowerCase();
  const cocok = (r) => !needle || [r.order_id, r.account_name, r.courier, r.order_channel,
    r.status_raw, r.status].some((v) => String(v || '').toLowerCase().includes(needle));
  const rows = allRows.filter(cocok);
  const isOpenBucket = bucket === 'lewat_batas' || bucket === 'belum_dikirim';
  const adaMenunggu = Number(t.belum_dikirim || 0) + Number(t.lewat_batas || 0) > 0;

  // Unduh = semua halaman kategori + toko yang dipilih (pencarian di layar ikut diterapkan)
  const ambilSemua = async () => {
    const out = [];
    for (let p = 1; p <= 100; p += 1) {
      const qs = new URLSearchParams({ bucket, page: String(p), page_size: '200' });
      if (accountId) qs.set('account_id', accountId);
      const r = await fetch(`${API}/api/marketing/orders/fulfillment-monitor?${qs}`, { headers });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.detail || 'Gagal');
      out.push(...(b.rows || []));
      if (p >= (b.total_pages || 1)) break;
    }
    return out.filter(cocok);
  };
  const kolomUnduh = isOpenBucket
    ? [
      { label: 'No. pesanan', nilai: (r) => r.order_id }, { label: 'Toko', nilai: (r) => r.account_name || '' },
      { label: 'Status', nilai: (r) => r.status_raw || r.status || '' }, { label: 'Pra-pesan', nilai: (r) => (r.is_preorder ? 'Ya' : 'Tidak') },
      { label: 'Dibayar', nilai: (r) => tgl(r.paid_at) }, { label: 'Menunggu (hari)', nilai: (r) => r.age_days ?? '' },
      { label: 'Batas (hari)', nilai: (r) => r.sla_days ?? '' }, { label: 'Lewat (hari)', nilai: (r) => r.over_by_days ?? '' },
      { label: 'Tenggat', nilai: (r) => tgl(r.deadline) }, { label: 'Kurir', nilai: (r) => r.courier || '' },
      { label: 'Kanal', nilai: (r) => r.order_channel || '' }, { label: 'Pcs', nilai: (r) => Number(r.quantity || 0) },
      { label: 'Nilai', nilai: (r) => Number(r.value || 0) },
    ]
    : [
      { label: 'No. pesanan', nilai: (r) => r.order_id }, { label: 'Toko', nilai: (r) => r.account_name || '' },
      { label: 'Status', nilai: (r) => r.status_raw || r.status || '' }, { label: 'Tanggal', nilai: (r) => tgl(r.order_date) },
      { label: 'Alasan', nilai: (r) => r.cancel_reason || '' }, { label: 'Pcs', nilai: (r) => Number(r.quantity || 0) },
      { label: 'Nilai', nilai: (r) => Number(r.value || 0) },
    ];

  const kolomPesanan = [
    { kunci: 'order', label: 'No. pesanan', hp: 'judul', isi: (r) => <span className="font-medium">{r.order_id}</span> },
    { kunci: 'toko', label: 'Toko', hp: 'keterangan', isi: (r) => r.account_name || '—' },
    { kunci: 'status', label: 'Status', isi: (r) => (
      <div className="flex flex-wrap gap-1">
        <StatusBadge status={r.status} label={r.status_raw || r.status} tone="default" />
        {r.is_preorder && <StatusBadge status="pre" label="Pra-pesan" tone="primary" />}
      </div>) },
    ...(isOpenBucket ? [
      { kunci: 'bayar', label: 'Dibayar', isi: (r) => <span className="md:whitespace-nowrap">{tgl(r.paid_at)}</span> },
      { kunci: 'umur', label: 'Menunggu', rata: 'kanan', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{r.age_days == null ? '—' : `${r.age_days} hari`}</span> },
      { kunci: 'batas', label: 'Batas', rata: 'kanan', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{r.sla_days} hari</span> },
      { kunci: 'lewat', label: 'Lewat', rata: 'kanan', isi: (r) => (r.late
        ? <span className="font-medium tabular-nums text-[hsl(var(--danger-text))]">+{r.over_by_days} hari</span>
        : <span className="text-muted-foreground">—</span>) },
      { kunci: 'tenggat', label: 'Tenggat', isi: (r) => <span className="text-muted-foreground md:whitespace-nowrap">{tgl(r.deadline)}</span> },
      { kunci: 'kurir', label: 'Kurir', isi: (r) => r.courier || '—' },
      { kunci: 'pcs', label: 'Pcs', rata: 'kanan', isi: (r) => <span className="tabular-nums">{num(r.quantity)}</span> },
      { kunci: 'nilai', label: 'Nilai', rata: 'kanan', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{rp(r.value)}</span> },
    ] : [
      { kunci: 'tgl', label: 'Tanggal', isi: (r) => <span className="md:whitespace-nowrap">{tgl(r.order_date)}</span> },
      { kunci: 'alasan', label: 'Alasan', isi: (r) => r.cancel_reason || '—' },
      { kunci: 'pcs', label: 'Pcs', rata: 'kanan', isi: (r) => <span className="tabular-nums">{num(r.quantity)}</span> },
      { kunci: 'nilai', label: 'Nilai', rata: 'kanan', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{rp(r.value)}</span> },
    ]),
  ];

  const perToko = data?.per_store || [];
  const kolomToko = [
    { kunci: 'toko', label: 'Toko', hp: 'judul', isi: (s) => <span className="font-medium">{s.account_name}</span> },
    { kunci: 'platform', label: 'Platform', hp: 'keterangan', isi: (s) => labelPlatform(s.platform) },
    { kunci: 'lewat', label: 'Lewat batas', rata: 'kanan', isi: (s) => (
      <span className={`tabular-nums ${s.lewat_batas ? 'font-medium text-[hsl(var(--danger-text))]' : ''}`}>{num(s.lewat_batas)}</span>) },
    { kunci: 'belum', label: 'Belum dikirim', rata: 'kanan', isi: (s) => <span className="tabular-nums">{num(s.belum_dikirim)}</span> },
    { kunci: 'nilai', label: 'Nilai tertahan', rata: 'kanan', isi: (s) => <span className="tabular-nums md:whitespace-nowrap">{rp(s.nilai_belum_dikirim)}</span> },
    { kunci: 'tua', label: 'Terlama (hari)', rata: 'kanan', isi: (s) => <span className="tabular-nums">{Number(s.umur_tertua_hari || 0).toLocaleString('id-ID', { maximumFractionDigits: 1 })}</span> },
    { kunci: 'sla', label: 'Batas normal / pra-pesan', rata: 'kanan', isi: (s) => <span className="tabular-nums">{s.sla_days} / {s.sla_days_preorder} hari</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <Button size="sm" variant="outline" onClick={() => setSlaStore(s)} data-testid={`monitor-sla-${s.account_code}`}>
        <Settings2 />Batas kirim
      </Button>) },
  ];

  // Toko yang belum punya pesanan tidak muncul di rekap per toko, jadi batas kirimnya tidak bisa disetel dari
  // tabel itu — padahal justru toko baru yang perlu disetel SEBELUM impor pertamanya.
  const tombolBatasToko = accountId && selectedAccount
    && !perToko.some((s) => s.account_id === accountId) && (
    <Button variant="outline" data-testid="monitor-sla-selected"
      onClick={() => setSlaStore({
        account_id: selectedAccount.id,
        account_code: selectedAccount.account_code,
        account_name: selectedAccount.account_name,
        sla_days: selectedAccount.ship_sla_days ?? data?.sla_default?.normal ?? 2,
        sla_days_preorder: selectedAccount.ship_sla_days_preorder ?? data?.sla_default?.preorder ?? 7,
      })}>
      <Settings2 />Batas kirim toko ini
    </Button>
  );

  return (
    <PageLayout testId="fulfillment-monitor-module" title="Monitoring kirim"
      subtitle="Pesanan yang harus dikejar hari ini: lewat batas kirim, belum dikirim, batal, dan retur."
      actions={tombolBatasToko || null}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="Cari no. pesanan, toko, kurir" value={q}
            onChange={(e) => setQ(e.target.value)} data-testid="monitor-search" />
        </div>
        <SmartNativeSelect className="w-56" value={accountId} data-testid="monitor-account"
          onChange={(e) => { setAccountId(e.target.value); setPage(1); }}>
          <option value="">Semua toko</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </SmartNativeSelect>
        <FilterChips value={bucket} hideWhenEmpty={false} testId="monitor-bucket"
          onChange={(k) => { setBucket(k); setPage(1); }}
          options={BUCKETS.map((b) => ({ key: b.key, label: b.label, count: num(t[b.key]) }))} />
      </>}
      tools={<>
        <TombolUnduh namaBerkas={`monitoring-kirim-${bucket}`} namaLembar="Pesanan" baris={rows} ambilSemua={ambilSemua}
          kolom={kolomUnduh} testId="monitor-export" />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="monitor-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Lewat batas kirim" value={num(t.lewat_batas)} accent="danger"
            sub={`Nilai ${rp(t.nilai_lewat_batas)}`} testId="tile-lewat-batas" />
          <StatTile label="Belum dikirim" value={num(t.belum_dikirim)} accent="warning"
            sub={`Nilai ${rp(t.nilai_belum_dikirim)}`} testId="tile-belum-dikirim" />
          <StatTile label="Menunggu terlama"
            value={adaMenunggu ? `${Number(t.umur_tertua_hari || 0).toLocaleString('id-ID', { maximumFractionDigits: 1 })} hari` : '—'}
            sub={adaMenunggu ? 'Sejak dibayar' : 'Tidak ada pesanan yang menunggu kirim'} testId="tile-tertua" />
          <StatTile label="Batal / retur" value={`${num(t.batal)} / ${num(t.retur)}`}
            sub="Perlu ekspor Batal-Retur dari Seller Center" testId="tile-batal" />
        </div>
        <p className="text-sm text-muted-foreground" data-testid="tile-dikirim">
          {num(t.pesanan_dibaca)} pesanan dibaca · {num(t.sudah_dikirim)} sudah dikirim.
        </p>
      </>}
      footer={data?.total_pages > 1 && (
        <PaginationLite page={page} totalPages={data.total_pages} onPageChange={setPage} total={data.total} pageSize={50} />
      )}>
      {(data?.data_notes || []).length > 0 && (
        <Notice tone="info" icon={Info} testId="monitor-data-notes">
          {data.data_notes.map((n, i) => <p key={i}>{n}</p>)}
        </Notice>
      )}

      {/* REKAP PER TOKO — ditampilkan walau hanya SATU toko yang berdata (tombol "Batas kirim" ada di sini). */}
      {perToko.length > 0 && (
        <section className="space-y-2" data-testid="monitor-per-store">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-base font-semibold">Per toko</p>
            <TombolUnduh namaBerkas="monitoring-kirim-per-toko" namaLembar="Per toko" baris={perToko} testId="monitor-per-store-unduh"
              kolom={[
                { label: 'Toko', nilai: (s) => s.account_name }, { label: 'Platform', nilai: (s) => labelPlatform(s.platform) },
                { label: 'Lewat batas', nilai: (s) => Number(s.lewat_batas || 0) }, { label: 'Belum dikirim', nilai: (s) => Number(s.belum_dikirim || 0) },
                { label: 'Nilai tertahan', nilai: (s) => Number(s.nilai_belum_dikirim || 0) },
                { label: 'Terlama (hari)', nilai: (s) => Number(s.umur_tertua_hari || 0) },
                { label: 'Batas normal (hari)', nilai: (s) => s.sla_days }, { label: 'Batas pra-pesan (hari)', nilai: (s) => s.sla_days_preorder },
              ]} />
          </div>
          <TabelData kolom={kolomToko} baris={perToko} kunci={(s) => s.account_id} testId="monitor-per-store-table" />
        </section>
      )}

      {/* daftar pesanan */}
      {loading && !data ? (
        <div className="space-y-2">{[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-8" />)}</div>
      ) : (
        <TabelData kolom={kolomPesanan} baris={rows} kunci={(r) => r.id || r.order_id} testId="monitor-table"
          kosong={<EmptyState icon={PackageCheck} testId="monitor-empty" title="Tidak ada pesanan pada kategori ini"
            description={t.pesanan_dibaca ? 'Tidak ada yang perlu dikejar di kategori ini.'
              : 'Belum ada pesanan sama sekali. Impor ekspor Seller Center dulu di menu Impor Data.'} />} />
      )}

      <SlaDialog open={!!slaStore} onOpenChange={(o) => !o && setSlaStore(null)}
        store={slaStore} token={token}
        onSaved={() => { load(); loadAccounts(); }} />
    </PageLayout>
  );
}

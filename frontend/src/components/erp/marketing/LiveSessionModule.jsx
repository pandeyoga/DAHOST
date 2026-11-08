/**
 * Sesi live (Live Selling › Sesi live) — catat & pantau performa sesi live shopping.
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub), akun toko = pilihan di baris penyaring
 * (dulu bar lebar ActiveAccountBar), 4 kartu angka StatTile (diperiksa vs data: 36 sesi, Rp1.097.428.252,
 * 7.043 pesanan, interaksi 88,38%, konversi 5,47%), tabel + unduh semua halaman, detail sesi di popup
 * (suka/komentar/dibagikan pindah ke popup & unduhan), label Indonesia.
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';
import React, { useState, useEffect, useCallback } from 'react';
import { Play, Plus, Pencil, Trash2, Package, AlertTriangle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { useToast } from '@/hooks/use-toast';
import { useActiveMarketingAccount } from '@/hooks/useActiveMarketingAccount';
import { useMarketingAccounts } from '@/hooks/useMarketingAccounts';
import { formatDateID } from '@/lib/format';
import axios from 'axios';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile } from '../moduleAtoms';
import LiveSessionDialog from './LiveSessionDialog';
import LiveSessionProductsDialog from './LiveSessionProductsDialog';

const API = process.env.REACT_APP_BACKEND_URL;

function fmt(n) { return new Intl.NumberFormat('id-ID').format(n || 0); }
function fmtRp(n) { return `Rp ${fmt(Math.round(n || 0))}`; }
const persen = (n) => `${String(Number(n || 0).toFixed(2)).replace('.', ',')}%`;

const PLATFORM = { shopee: 'Shopee', tiktok: 'TikTok', instagram: 'Instagram', tokopedia: 'Tokopedia' };
const labelPlatform = (p) => PLATFORM[p] || (p ? p.charAt(0).toUpperCase() + p.slice(1) : '—');

// Pilihan akun toko di baris penyaring (pengganti ActiveAccountBar) — pilihan yang sama tersimpan lewat
// useActiveMarketingAccount, jadi layar Marketing lain ikut.
function PilihAkun({ accounts = [], activeAccount, onChange, testId = 'pilih-akun', lebar = 'w-56' }) {
  const aktif = accounts.filter((a) => a.status === 'active' || !a.status);
  const daftar = activeAccount && !aktif.some((a) => a.id === activeAccount.id) ? [activeAccount, ...aktif] : aktif;
  return (
    <SmartNativeSelect value={activeAccount?.id || ''} className={lebar} data-testid={testId}
      onChange={(e) => onChange(daftar.find((a) => a.id === e.target.value) || null)}>
      <option value="">Semua toko</option>
      {daftar.map((a) => <option key={a.id} value={a.id}>{`${a.account_name} · ${labelPlatform(a.platform)}`}</option>)}
    </SmartNativeSelect>
  );
}

export default function LiveSessionModule({ token }) {
  const { toast } = useToast();
  const { activeAccount, setActiveAccount } = useActiveMarketingAccount();
  const { accounts: masterAccounts } = useMarketingAccounts(token);
  const [summary, setSummary] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);

  const [platformFilter, setPlatformFilter] = useState('');
  const [page, setPage] = useState(1);
  // F16 — sesi live kini bisa DICATAT dari layar (dulu hanya bisa dibaca).
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  // F18#3 — rincian produk per sesi (menjawab "barang mana yang paling laku").
  const [productsFor, setProductsFor] = useState(null);
  const [detail, setDetail] = useState(null);

  const authH = { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };

  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      // F14 — ringkasan dilingkupi toko yang SAMA dengan tabelnya. Sebelum ini
      // kartu KPI menghitung seluruh toko sementara tabel difilter, sehingga satu
      // layar menampilkan dua kenyataan.
      const res = await axios.get(`${API}/api/marketing/live/summary`, {
        headers: authH,
        params: activeAccount?.id ? { account_id: activeAccount.id } : {},
      });
      if (res.data.success) {
        setSummary(res.data.data);
      }
    } catch (e) {
      toast({ title: 'Gagal memuat ringkasan live', variant: 'destructive' });
    } finally {
      setSummaryLoading(false);
    }
  }, [token, activeAccount]); // eslint-disable-line

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: 20 };
      if (platformFilter) params.platform = platformFilter;
      if (activeAccount?.id) params.account_id = activeAccount.id;
      const res = await axios.get(`${API}/api/marketing/live/sessions`, { params, headers: authH });
      if (res.data.success) {
        setSessions(res.data.data.sessions || []);
        setPagination(res.data.pagination);
      }
    } catch (e) {
      toast({ title: 'Gagal memuat sesi live', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
    // 8 Nov 2026: activeAccount ikut — dulu ganti toko hanya memuat ulang kartu, tabelnya tetap toko lama (F14).
  }, [page, platformFilter, token, activeAccount]); // eslint-disable-line

  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchSessions(); }, [fetchSessions]);

  const ambilSemua = async () => {
    const semua = [];
    for (let p = 1; p <= 200; p += 1) {
      const params = { page: p, page_size: 100 };
      if (platformFilter) params.platform = platformFilter;
      if (activeAccount?.id) params.account_id = activeAccount.id;
      const res = await axios.get(`${API}/api/marketing/live/sessions`, { params, headers: authH });
      semua.push(...(res.data.data?.sessions || []));
      if (p >= (res.data.pagination?.total_pages || 1)) break;
    }
    return semua;
  };

  const hapus = async (s) => {
    if (!(await confirmDialog({ title: `Hapus sesi "${s.title}"?`, confirmLabel: 'Hapus', danger: true }))) return;
    try {
      await axios.delete(`${API}/api/marketing/live/sessions/${s.id}`, { headers: authH });
      toast({ title: 'Sesi live dihapus' });
      setDetail(null);
      fetchSessions(); fetchSummary();
    } catch (e) {
      toast({ title: 'Gagal menghapus', description: e.response?.data?.detail, variant: 'destructive' });
    }
  };
  const ubah = (s) => { setDetail(null); setEditing(s); setDialogOpen(true); };
  const rincian = (s) => { setDetail(null); setProductsFor(s); };
  // Waktu dari server tanpa zona = UTC → tambah 'Z' supaya dibaca benar dalam WIB.
  const tgl = (s) => (s.session_date ? formatDateID(/T\d\d:\d\d(:\d\d(\.\d+)?)?$/.test(String(s.session_date)) ? `${s.session_date}Z` : s.session_date) : '—');

  const isiProduk = (s) => ((s.products_detail?.lines_count || 0) === 0 ? (
    <span className="text-muted-foreground">Belum diisi</span>
  ) : (
    <span className="text-sm">
      <span className="tabular-nums">{s.products_detail.lines_count} produk · {fmt(s.products_detail.total_units)} unit</span>
      <span className={`flex items-center gap-1 text-xs tabular-nums ${s.products_detail.over_allocated ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>
        {s.products_detail.over_allocated && <AlertTriangle className="h-3 w-3" />}
        {fmtRp(s.products_detail.total_revenue)}{s.products_detail.coverage_pct ? ` (${s.products_detail.coverage_pct}%)` : ''}
      </span>
    </span>
  ));

  const kolom = [
    { kunci: 'judul', label: 'Sesi', hp: 'judul', isi: (s) => (
      <span className="block max-w-[220px]"><span className="block truncate font-medium" title={s.title}>{s.title}</span>
        <span className="block truncate text-xs text-muted-foreground" title={s.account_name}>{s.account_name || '—'}</span></span>) },
    { kunci: 'tgl', label: 'Tanggal', hp: 'keterangan', isi: (s) => <span className="tabular-nums md:whitespace-nowrap">{tgl(s)}</span> },
    { kunci: 'platform', label: 'Platform', isi: (s) => labelPlatform(s.platform) },
    { kunci: 'host', label: 'Host', isi: (s) => s.host_name || '—' },
    { kunci: 'durasi', label: 'Durasi', rata: 'kanan', isi: (s) => <span className="tabular-nums md:whitespace-nowrap">{fmt(s.duration_minutes)} menit</span> },
    { kunci: 'penonton', label: 'Penonton', rata: 'kanan', isi: (s) => (
      <span className="tabular-nums">{fmt(s.total_viewers)}<span className="block text-xs text-muted-foreground">puncak {fmt(s.peak_viewers)}</span></span>) },
    { kunci: 'pesanan', label: 'Pesanan', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmt(s.orders)}</span> },
    { kunci: 'omzet', label: 'Omzet', rata: 'kanan', hp: 'nilai', isi: (s) => <span className="font-medium tabular-nums md:whitespace-nowrap">{fmtRp(s.revenue)}</span> },
    { kunci: 'cvr', label: 'Konversi', rata: 'kanan', isi: (s) => <span className="tabular-nums">{persen(s.conversion_rate)}</span> },
    // F18#3 — kolom rincian produk: dulu tidak ada jalan mengisinya sehingga laporan "produk terlaris saat live" selalu kosong.
    { kunci: 'produk', label: 'Rincian produk', isi: isiProduk },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
        <Button size="icon-sm" variant="ghost" title="Rincian produk terjual pada sesi ini" aria-label="Rincian produk"
          data-testid={`live-products-${s.id}`} onClick={() => setProductsFor(s)}><Package /></Button>
        <Button size="icon-sm" variant="ghost" title="Ubah sesi" aria-label="Ubah sesi"
          data-testid={`live-edit-${s.id}`} onClick={() => { setEditing(s); setDialogOpen(true); }}><Pencil /></Button>
        <Button size="icon-sm" variant="ghost" className="text-[hsl(var(--danger-text))]" title="Hapus sesi" aria-label="Hapus sesi"
          data-testid={`live-delete-${s.id}`} onClick={() => hapus(s)}><Trash2 /></Button>
      </div>) },
  ];

  const topHosts = summary?.top_hosts || [];
  const kolomUnduh = [
    { label: 'Judul', nilai: (s) => s.title || '' }, { label: 'Akun toko', nilai: (s) => s.account_name || '' },
    { label: 'Platform', nilai: (s) => labelPlatform(s.platform) }, { label: 'Host', nilai: (s) => s.host_name || '' },
    { label: 'Tanggal', nilai: tgl }, { label: 'Durasi (menit)', nilai: (s) => Number(s.duration_minutes) || 0 },
    { label: 'Penonton', nilai: (s) => Number(s.total_viewers) || 0 }, { label: 'Penonton puncak', nilai: (s) => Number(s.peak_viewers) || 0 },
    { label: 'Suka', nilai: (s) => Number(s.likes) || 0 }, { label: 'Komentar', nilai: (s) => Number(s.comments) || 0 },
    { label: 'Dibagikan', nilai: (s) => Number(s.shares) || 0 }, { label: 'Pesanan', nilai: (s) => Number(s.orders) || 0 },
    { label: 'Omzet', nilai: (s) => Number(s.revenue) || 0 }, { label: 'Konversi (%)', nilai: (s) => Number(s.conversion_rate) || 0 },
    { label: 'Interaksi (%)', nilai: (s) => Number(s.engagement_rate) || 0 },
    { label: 'Produk dirinci', nilai: (s) => s.products_detail?.lines_count || 0 },
  ];

  return (
    <PageLayout testId="live-dashboard" title="Sesi live" subtitle="Performa live shopping di semua platform."
      actions={<Button data-testid="live-add-btn" onClick={() => { setEditing(null); setDialogOpen(true); }}><Plus />Catat sesi live</Button>}
      filters={<>
        <PilihAkun accounts={masterAccounts} activeAccount={activeAccount} testId="live-account"
          onChange={(acc) => { setActiveAccount(acc); setPage(1); }} />
        <SmartNativeSelect value={platformFilter} onChange={(e) => { setPlatformFilter(e.target.value); setPage(1); }} className="w-40"
          searchable={false} data-testid="live-platform-filter">
          <option value="">Semua platform</option>
          <option value="shopee">Shopee</option>
          <option value="tiktok">TikTok</option>
          <option value="instagram">Instagram</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="sesi-live" namaLembar="Sesi live" baris={sessions} ambilSemua={ambilSemua} kolom={kolomUnduh} testId="live-unduh" />
        <Button variant="outline" size="icon" onClick={() => { fetchSummary(); fetchSessions(); }} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading || summaryLoading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="live-kpi">
          <StatTile label="Jumlah sesi" value={summaryLoading ? '…' : fmt(summary?.total_sessions)}
            sub={summaryLoading ? '' : `${fmt(summary?.total_viewers)} penonton`} hint="Semua sesi yang tercatat untuk akun toko terpilih." />
          <StatTile label="Omzet live" value={summaryLoading ? '…' : fmtRp(summary?.total_revenue)}
            sub={summaryLoading ? '' : `${fmt(summary?.total_orders)} pesanan`} hint="Jumlah omzet yang dicatat per sesi." />
          <StatTile label="Rata-rata interaksi" value={summaryLoading ? '…' : persen(summary?.avg_engagement_rate)} sub="Rata-rata per sesi"
            hint="(Suka + komentar + dibagikan) ÷ penonton × 100, dirata-rata per sesi. Bisa lebih dari 100%." />
          <StatTile label="Rata-rata konversi" value={summaryLoading ? '…' : persen(summary?.avg_conversion_rate)} sub="Rata-rata per sesi"
            hint="Pesanan ÷ penonton × 100, dirata-rata per sesi." />
        </div>
      }
      footer={pagination && pagination.total_pages > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm text-muted-foreground">{fmt(pagination.total)} sesi</span>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>Sebelumnya</Button>
            <span className="text-sm tabular-nums">{page} / {pagination.total_pages}</span>
            <Button size="sm" variant="outline" disabled={page >= pagination.total_pages} onClick={() => setPage((p) => p + 1)}>Berikutnya</Button>
          </div>
        </div>
      )}>
      {topHosts.length > 0 && (
        <section className="space-y-2">
          <div className="flex items-center gap-2">
            <p className="flex-1 text-base font-semibold">Host dengan omzet tertinggi</p>
            <TombolUnduh namaBerkas="host-live-teratas" baris={topHosts} testId="live-unduh-host"
              kolom={[{ label: 'Peringkat', nilai: (h) => topHosts.indexOf(h) + 1 }, { label: 'Host', nilai: (h) => h.host },
                { label: 'Sesi', nilai: (h) => h.sessions }, { label: 'Omzet', nilai: (h) => Number(h.revenue) || 0 }]} />
          </div>
          <TabelData baris={topHosts} kunci={(r) => r.host} testId="live-top-hosts" kolom={[
            { kunci: 'r', label: 'Peringkat', isi: (h) => <span className="tabular-nums text-muted-foreground">#{topHosts.indexOf(h) + 1}</span> },
            { kunci: 'host', label: 'Host', hp: 'judul', isi: (h) => <span className="font-medium">{h.host}</span> },
            { kunci: 'sesi', label: 'Sesi', rata: 'kanan', hp: 'keterangan', isi: (h) => <span className="tabular-nums">{fmt(h.sessions)} sesi</span> },
            { kunci: 'omzet', label: 'Omzet', rata: 'kanan', hp: 'nilai', isi: (h) => <span className="tabular-nums">{fmtRp(h.revenue)}</span> },
          ]} />
        </section>
      )}

      {loading && sessions.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat sesi live…</p>
      ) : (
        <TabelData kolom={kolom} baris={sessions} testId="live-sessions-table" onKlikBaris={setDetail}
          kosong={<EmptyState icon={Play} title="Belum ada sesi live"
            description={activeAccount?.id
              ? `Toko ${activeAccount.account_name} belum punya sesi live. Catat sesi live, atau impor massal lewat Impor data › Sesi live selling.`
              : 'Catat sesi live, atau impor massal lewat Impor data › Sesi live selling.'} />} />
      )}

      <DetailPopup open={!!detail} onClose={() => setDetail(null)} judul={detail?.title}
        keterangan={detail && `${labelPlatform(detail.platform)} · ${detail.account_name || '—'} · ${tgl(detail)}`} testId="live-detail"
        aksi={detail && <>
          <Button variant="outline" className="text-[hsl(var(--danger-text))]" onClick={() => hapus(detail)}><Trash2 />Hapus</Button>
          <Button variant="outline" onClick={() => rincian(detail)}><Package />Rincian produk</Button>
          <Button onClick={() => ubah(detail)}><Pencil />Ubah</Button>
        </>}>
        {detail && <>
          <BarisDetail label="Host">{detail.host_name || '—'}</BarisDetail>
          <BarisDetail label="Durasi">{fmt(detail.duration_minutes)} menit</BarisDetail>
          <BarisDetail label="Penonton">{fmt(detail.total_viewers)} (puncak {fmt(detail.peak_viewers)})</BarisDetail>
          <BarisDetail label="Suka · komentar · dibagikan">{fmt(detail.likes)} · {fmt(detail.comments)} · {fmt(detail.shares)}</BarisDetail>
          <BarisDetail label="Interaksi">{persen(detail.engagement_rate)}</BarisDetail>
          <BarisDetail label="Pesanan">{fmt(detail.orders)}</BarisDetail>
          <BarisDetail label="Omzet">{fmtRp(detail.revenue)}</BarisDetail>
          <BarisDetail label="Konversi">{persen(detail.conversion_rate)}</BarisDetail>
          <BarisDetail label="Rincian produk">{isiProduk(detail)}</BarisDetail>
        </>}
      </DetailPopup>

      <LiveSessionDialog
        open={dialogOpen}
        session={editing}
        token={token}
        onClose={() => { setDialogOpen(false); setEditing(null); }}
        onSaved={() => { fetchSessions(); fetchSummary(); }}
      />

      <LiveSessionProductsDialog
        open={!!productsFor}
        session={productsFor}
        token={token}
        onClose={() => setProductsFor(null)}
        onSaved={() => { fetchSessions(); fetchSummary(); }}
      />
    </PageLayout>
  );
}

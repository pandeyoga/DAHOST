/**
 * DashboardGrafik — bagian grafik Dashboard Marketing selain penjualan (owner 13 Nov 2026: "untuk dashboard marketing
 * saya lihat grafik hanya sales saja padahal bisa ada ads, anggaran realisasi dll.").
 *
 * SATU SUMBER: tiap bagian membaca endpoint yang SAMA dengan layar sumbernya, dengan periode & toko layar ini:
 *   • Iklan            → `/api/marketing/ads/summary` + `/ads/performance-trend` (Laporan Marketing › Performa iklan)
 *   • Anggaran         → `/api/marketing/cycle/overview` (Target & Anggaran › Siklus) atau, untuk minggu Senin saat
 *                        anggaran disusun mingguan, `/api/marketing/budget/summary` (Target & Anggaran › Anggaran)
 *   • Target per toko  → `/api/marketing/cycle/overview` (Target & Anggaran › Siklus)
 *   • Live selling     → `/api/marketing/dashboard/overview` (kartu "Termasuk live" — definisi omzet live resmi)
 *   • KOL / kreator    → `/api/marketing/targets/creator/monthly-summary` (Target & Anggaran › Target KOL)
 * Layar tidak menjumlah angka bisnis sendiri; izin tiap data tetap mengikuti centang modul sumbernya (403 = pesan).
 * Tabel & keadaan kosong selalu tampil (keputusan owner 8 Nov 2026), grafik semua-nol diganti EmptyState.
 */
import { useEffect, useState } from 'react';
import { AlertTriangle, ArrowRight, Megaphone, Radio, Target, Users, Wallet } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatNumber, formatRupiah } from '@/lib/format';
import { cn } from '@/lib/utils';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import GrafikAsisten from '../asisten/GrafikAsisten';
import {
  CATATAN_KELOMPOK, STATUS_CAPAIAN, adaNilai, barisAnggaran, barisKreator, barisTarget, labelBulanMarketing,
  labelMinggu, labelSaluranIklan, namaBulan, pesanGagal, rapikanHarian, spec,
} from './dashboardGrafikData';

const API = process.env.REACT_APP_BACKEND_URL;
const fmtRp = formatRupiah;
// Kolom berjudul "(Rp)": angka tanpa "Rp", negatif "−1.234.567" (PANDUAN_UI G7) — tabel muat di kolom setengah layar.
const rpKolom = (v) => {
  const n = Math.round(Number(v || 0));
  return n < 0 ? `−${formatNumber(-n)}` : formatNumber(n);
};
const desimal = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 });
const persen = (n) => (n === null || n === undefined ? '—' : `${Number(n).toLocaleString('id-ID', { maximumFractionDigits: 1 })}%`);
const angka = (n) => Number(n || 0).toLocaleString('id-ID');
const merahBilaMinus = (v) => (Number(v) < 0 ? 'text-[hsl(var(--danger-text))]' : '');

const MODUL_IKLAN = 'modul "Kalender Konten, Diskon, Iklan & Peluncuran"';
const MODUL_ANGGARAN = 'modul "Target & Anggaran"';
const MODUL_SIKLUS = 'modul "Target & Anggaran" (Portal Manajemen)';

/** Ambil JSON; `url` kosong = tidak mengambil. Galat membawa `status` & `detail` server. */
export function useAmbilJson(url, token, muatUlang = 0) {
  const [st, setSt] = useState({ data: null, galat: null, loading: !!url });
  useEffect(() => {
    if (!url) { setSt({ data: null, galat: null, loading: false }); return undefined; }
    let hidup = true;
    setSt((s) => ({ ...s, loading: true, galat: null }));
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        if (!r.ok) {
          const e = new Error('gagal');
          e.status = r.status;
          e.detail = body?.detail;
          throw e;
        }
        return body;
      })
      .then((data) => { if (hidup) setSt({ data, galat: null, loading: false }); })
      .catch((e) => { if (hidup) setSt({ data: null, galat: { status: e.status, detail: e.detail }, loading: false }); });
    return () => { hidup = false; };
  }, [url, token, muatUlang]);
  return st;
}

/** Buka tab tertentu sebuah hub (pola `makeRedirect`: `hub_tab_<hubId>`). */
export function bukaHubTab(onNavigate, hubId, tab) {
  try { if (tab) sessionStorage.setItem(`hub_tab_${hubId}`, tab); } catch (e) { /* sessionStorage tidak tersedia */ }
  onNavigate?.(hubId);
}

/** Kepala satu bagian: judul + satu kalimat, alat (unduh) & tautan ke layar sumber di kanan, ringkasan di bawah. */
export function BagianGrafik({ judul, keterangan, ringkasan, alat, tautan, children, testId, className }) {
  return (
    <section className={cn('min-w-0 space-y-2', className)} data-testid={testId}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-base font-semibold">{judul}</p>
          {keterangan && <p className="text-sm text-muted-foreground">{keterangan}</p>}
        </div>
        {(alat || tautan) && <div className="flex flex-wrap items-center gap-2">{alat}{tautan}</div>}
      </div>
      {ringkasan && <p className="text-sm text-muted-foreground" data-testid={`${testId}-ringkasan`}>{ringkasan}</p>}
      {children}
    </section>
  );
}

export function TautanSumber({ label, onClick, testId }) {
  return (
    <Button variant="link" size="sm" className="h-auto p-0" onClick={onClick} data-testid={testId}>
      {label}<ArrowRight />
    </Button>
  );
}

/** Grafik, atau memuat / galat / kosong — kotak grafik tidak pernah hilang dari layar. */
export function KotakGrafik({ spesifikasi, loading, galat, kosong, testId, tombolAngka = true }) {
  if (loading) return <Skeleton className="h-[260px] w-full" data-testid={`${testId}-memuat`} />;
  if (galat) {
    return <Notice tone="warning" icon={AlertTriangle} testId={`${testId}-galat`}>{galat}</Notice>;
  }
  if (!adaNilai(spesifikasi)) {
    return (
      <div className="rounded-[var(--radius-md)] border border-[var(--glass-border)] [&>div]:py-8" data-testid={`${testId}-kosong`}>
        {kosong}
      </div>
    );
  }
  return <GrafikAsisten spec={spesifikasi} testId={testId} tombolAngka={tombolAngka} />;
}

const galatDari = (st, modul) => (st?.galat ? pesanGagal(st.galat.status, modul, st.galat.detail) : '');

// ── Iklan ─────────────────────────────────────────────────────────────────────────────────────
export function BagianIklan({ token, periode, tokoId, muatUlang, onNavigate }) {
  const q = new URLSearchParams({ date_from: periode.date_from, date_to: periode.date_to });
  if (tokoId) q.set('account_id', tokoId);
  const ring = useAmbilJson(`${API}/api/marketing/ads/summary?${q}`, token, muatUlang);
  const tren = useAmbilJson(`${API}/api/marketing/ads/performance-trend?${q}`, token, muatUlang);
  const s = ring.data?.data;
  const galat = galatDari(ring, MODUL_IKLAN) || galatDari(tren, MODUL_IKLAN);
  const rapi = rapikanHarian(tren.data?.data?.trend, ['spend', 'revenue']);
  const sp = spec('garis', rapi.baris, [{ kunci: 'spend', nama: 'Biaya iklan' }, { kunci: 'revenue', nama: 'Omzet dari iklan' }],
    { catatan: CATATAN_KELOMPOK[rapi.satuan] });
  const saluran = Object.entries(s?.by_platform || {})
    .map(([kode, v]) => ({ kode, nama: labelSaluranIklan(kode), ...v }))
    .sort((a, b) => Number(b.spend || 0) - Number(a.spend || 0));
  const adaBiaya = Number(s?.total_spend || 0) > 0;
  const buka = () => bukaHubTab(onNavigate, 'marketing-reports', 'ads');
  return (
    <BagianGrafik testId="dash-iklan" judul="Iklan: biaya, omzet, ROAS"
      keterangan="Biaya iklan dan omzet yang dilaporkan platform iklan per hari — sumber sama dengan Laporan Marketing › Performa iklan."
      ringkasan={!galat && adaBiaya ? (
        <>Biaya iklan <b className="text-foreground">{fmtRp(s.total_spend)}</b> · omzet dari iklan{' '}
          <b className="text-foreground">{fmtRp(s.total_revenue)}</b> · ROAS <b className="text-foreground">{desimal(s.overall_roas)}×</b>{' '}
          (omzet iklan ÷ biaya iklan){Number(s.dibagi_rata || 0) > 0 ? ` · ${s.dibagi_rata} laporan berperiode dibagi rata per hari` : ''}</>
      ) : null}
      alat={(
        <TombolUnduh namaBerkas={`iklan-per-saluran-${periode.date_from}-${periode.date_to}`} namaLembar="Iklan per saluran" baris={saluran}
          testId="dash-iklan-unduh"
          kolom={[
            { label: 'Saluran iklan', nilai: (r) => r.nama }, { label: 'Biaya iklan (Rp)', nilai: (r) => Number(r.spend || 0) },
            { label: 'Omzet dari iklan (Rp)', nilai: (r) => Number(r.revenue || 0) }, { label: 'ROAS', nilai: (r) => Number(r.roas || 0) },
            { label: 'Baris data', nilai: (r) => Number(r.campaigns || 0) },
          ]} />
      )}
      tautan={<TautanSumber label="Performa iklan" onClick={buka} testId="dash-iklan-buka" />}>
      <KotakGrafik testId="dash-iklan-grafik" spesifikasi={sp} loading={ring.loading || tren.loading} galat={galat}
        kosong={<EmptyState icon={Megaphone} title="Belum ada biaya iklan pada periode ini"
          description="Biaya iklan dicatat di Laporan Marketing › Performa iklan (Input biaya iklan) atau lewat Impor Data › Iklan."
          action={<Button variant="outline" onClick={buka}>Buka performa iklan</Button>} />} />
      <TabelData baris={saluran} kunci={(r) => r.kode} testId="dash-iklan-saluran"
        kosong={<EmptyState icon={Megaphone} title={galat ? 'Data iklan tidak bisa dimuat' : 'Belum ada biaya iklan per saluran'}
          description={galat || 'Rincian per saluran muncul setelah ada biaya iklan di periode ini.'} />}
        kolom={[
          { kunci: 'nama', label: 'Saluran iklan', hp: 'judul', isi: (r) => (
            <div><p className="font-medium">{r.nama}</p><p className="text-xs text-muted-foreground">{angka(r.campaigns)} baris data</p></div>) },
          { kunci: 'spend', label: 'Biaya (Rp)', rata: 'kanan', isi: (r) => <span className="tabular-nums">{rpKolom(r.spend)}</span> },
          { kunci: 'revenue', label: 'Omzet iklan (Rp)', rata: 'kanan', isi: (r) => <span className="tabular-nums">{rpKolom(r.revenue)}</span> },
          { kunci: 'roas', label: 'ROAS', rata: 'kanan', isi: (r) => <span className="tabular-nums">{Number(r.spend || 0) > 0 ? `${desimal(r.roas)}×` : '—'}</span> },
        ]} />
    </BagianGrafik>
  );
}

// ── Anggaran vs realisasi ─────────────────────────────────────────────────────────────────────
export function BagianAnggaran({ token, info, tokoId, siklus, muatUlang, onNavigate }) {
  // Setelan periode anggaran (Target & Anggaran › Anggaran): mingguan Senin (bawaan) atau bulanan.
  const setelan = useAmbilJson(`${API}/api/marketing/budget/period-settings`, token, muatUlang);
  const st = setelan.data?.settings;
  const susunMingguan = st?.period_mode === 'weekly' && Number(st?.period_days) === 7;
  const mingguan = info.jenis === 'minggu' && susunMingguan;
  const urlMinggu = mingguan
    ? `${API}/api/marketing/budget/summary?period=${info.minggu}${tokoId ? `&account_id=${encodeURIComponent(tokoId)}` : ''}`
    : null;
  const minggu = useAmbilJson(urlMinggu, token, muatUlang);

  const loading = info.jenis === 'minggu' && setelan.loading ? true : (mingguan ? minggu.loading : siklus.loading);
  const galat = mingguan ? galatDari(minggu, MODUL_ANGGARAN) : galatDari(siklus, MODUL_SIKLUS);
  const cats = mingguan ? minggu.data?.categories : siklus.data?.totals?.budget_categories;
  const baris = galat ? [] : barisAnggaran(cats);
  const totalRencana = mingguan ? Number(minggu.data?.total_budget || 0) : Number(siklus.data?.totals?.total_plan || 0);
  const totalPakai = mingguan ? Number(minggu.data?.total_spend || 0) : Number(siklus.data?.totals?.total_spend || 0);
  const labelPeriode = mingguan ? `minggu ${labelMinggu(info.minggu)}` : `bulan ${labelBulanMarketing(info.bulan)}`;
  const sp = spec('batang_horizontal', baris, [{ kunci: 'plan', nama: 'Rencana' }, { kunci: 'spend', nama: 'Terpakai' }]);
  const buka = () => onNavigate?.('marketing-targets');

  const catatan = [
    info.jenis === 'minggu' && st && !mingguan
      && 'Periode anggaran tidak disusun per minggu Senin, jadi yang tampil anggaran bulan Marketing tempat minggu ini berakhir.',
    info.jenis === 'rentang' && 'Anggaran dibaca per bulan Marketing tempat tanggal akhir periode berada.',
    info.jenis !== 'minggu' && susunMingguan
      && 'Rencana mingguan tidak ikut di rencana bulanan ini; pilih "Minggu ini" atau "Minggu lalu" untuk melihatnya.',
  ].filter(Boolean).join(' ');

  return (
    <BagianGrafik testId="dash-anggaran" judul="Anggaran vs realisasi"
      keterangan={`Rencana dan biaya terpakai per kategori, ${labelPeriode} — sama dengan Target & Anggaran.`}
      ringkasan={!loading && !galat ? (
        <>{totalRencana > 0
          ? <>Terpakai <b className="text-foreground">{fmtRp(totalPakai)}</b> dari rencana <b className="text-foreground">{fmtRp(totalRencana)}</b>{' '}
            ({persen(totalPakai / totalRencana * 100)}) · {totalPakai > totalRencana
              ? <>lewat rencana <b className="text-[hsl(var(--danger-text))]">{fmtRp(totalPakai - totalRencana)}</b></>
              : <>sisa <b className="text-foreground">{fmtRp(totalRencana - totalPakai)}</b></>}</>
          : <>Belum ada rencana anggaran · terpakai <b className="text-foreground">{fmtRp(totalPakai)}</b></>}
          {catatan ? ` · ${catatan}` : ''}</>
      ) : null}
      alat={(
        <TombolUnduh namaBerkas={`anggaran-${mingguan ? info.minggu : info.bulan}`} namaLembar="Anggaran per kategori" baris={baris}
          testId="dash-anggaran-unduh"
          kolom={[
            { label: 'Kategori', nilai: (r) => r.label }, { label: 'Cara hitung', nilai: (r) => (r.mode === 'auto' ? 'Otomatis' : 'Isi manual') },
            { label: 'Rencana (Rp)', nilai: (r) => r.plan }, { label: 'Terpakai (Rp)', nilai: (r) => r.spend },
            { label: 'Sisa (Rp)', nilai: (r) => r.remaining }, { label: 'Terpakai (%)', nilai: (r) => (r.used_pct == null ? '' : r.used_pct) },
          ]} />
      )}
      tautan={<TautanSumber label="Target & anggaran" onClick={buka} testId="dash-anggaran-buka" />}>
      <KotakGrafik testId="dash-anggaran-grafik" spesifikasi={sp} loading={loading} galat={galat} tombolAngka={false}
        kosong={<EmptyState icon={Wallet} title="Belum ada rencana maupun biaya terpakai"
          description="Rencana anggaran diisi di Target & Anggaran; biaya iklan, diskon, kreator, dan host live terhitung otomatis."
          action={<Button variant="outline" onClick={buka}>Buka target & anggaran</Button>} />} />
      <TabelData baris={loading ? [] : baris} kunci={(r) => r.category} testId="dash-anggaran-tabel"
        kosong={<EmptyState icon={Wallet} title={galat ? 'Anggaran tidak bisa dimuat' : 'Memuat anggaran…'} description={galat || undefined} />}
        kolom={[
          { kunci: 'label', label: 'Kategori', hp: 'judul', isi: (r) => (
            <div><p className="font-medium">{r.label}</p>
              <p className="text-xs text-muted-foreground">{r.mode === 'auto' ? 'Dihitung otomatis' : 'Diisi manual'}</p></div>) },
          { kunci: 'plan', label: 'Rencana (Rp)', rata: 'kanan', isi: (r) => <span className="tabular-nums">{rpKolom(r.plan)}</span> },
          { kunci: 'spend', label: 'Terpakai (Rp)', rata: 'kanan', isi: (r) => <span className="font-medium tabular-nums">{rpKolom(r.spend)}</span> },
          { kunci: 'sisa', label: 'Sisa (Rp)', rata: 'kanan', isi: (r) => <span className={cn('tabular-nums', merahBilaMinus(r.remaining))}>{rpKolom(r.remaining)}</span> },
          { kunci: 'pct', label: 'Pakai', rata: 'kanan', isi: (r) => <span className="tabular-nums">{persen(r.used_pct)}</span> },
        ]} />
    </BagianGrafik>
  );
}

// ── Pencapaian target per toko ────────────────────────────────────────────────────────────────
export function BagianTarget({ info, siklus, onNavigate }) {
  const galat = galatDari(siklus, MODUL_SIKLUS);
  const baris = galat ? [] : barisTarget(siklus.data?.rows);
  const t = siklus.data?.totals || {};
  const prog = siklus.data?.progress || {};
  const adaTarget = baris.some((r) => r.target > 0);
  const sp = spec('batang_horizontal', adaTarget ? baris : [], [{ kunci: 'target', nama: 'Target omzet' }, { kunci: 'omzet', nama: 'Omzet' }],
    { label: 'toko' });
  const buka = () => onNavigate?.('marketing-targets');
  return (
    <BagianGrafik testId="dash-target" judul="Pencapaian target per toko"
      keterangan={`Target omzet vs omzet bulan ${labelBulanMarketing(info.bulan)} — sama dengan Target & Anggaran › Siklus.`}
      ringkasan={!siklus.loading && !galat && adaTarget ? (
        <>Capaian gabungan <b className="text-foreground">{persen(t.revenue_pct)}</b> dari {angka(t.accounts_with_target)} toko bertarget ·
          laju bulan {persen(t.pace_pct)} (hari ke-{angka(prog.days_elapsed)} dari {angka(prog.days_total)})</>
      ) : null}
      alat={(
        <TombolUnduh namaBerkas={`target-per-toko-${info.bulan}`} namaLembar="Target per toko" baris={baris} testId="dash-target-unduh"
          kolom={[
            { label: 'Toko', nilai: (r) => r.toko }, { label: 'Kode', nilai: (r) => r.kode },
            { label: 'Target omzet (Rp)', nilai: (r) => r.target }, { label: 'Omzet (Rp)', nilai: (r) => r.omzet },
            { label: 'Capaian (%)', nilai: (r) => (r.capaian == null ? '' : r.capaian) },
            { label: 'Status', nilai: (r) => (STATUS_CAPAIAN[r.status] || STATUS_CAPAIAN.no_target).label },
          ]} />
      )}
      tautan={<TautanSumber label="Target & anggaran" onClick={buka} testId="dash-target-buka" />}>
      <KotakGrafik testId="dash-target-grafik" spesifikasi={sp} loading={siklus.loading} galat={galat} tombolAngka={false}
        kosong={<EmptyState icon={Target} title={`Belum ada target omzet bulan ${namaBulan(info.bulan)}`}
          description="Target per toko diisi di Target & Anggaran › Target akun."
          action={<Button variant="outline" onClick={buka}>Isi target</Button>} />} />
      <TabelData baris={siklus.loading ? [] : baris} kunci={(r) => r.account_id} testId="dash-target-tabel"
        kosong={<EmptyState icon={Target} title={galat ? 'Target tidak bisa dimuat' : (siklus.loading ? 'Memuat target…' : 'Belum ada toko aktif')}
          description={galat || undefined} />}
        kolom={[
          { kunci: 'toko', label: 'Toko', hp: 'judul', isi: (r) => (
            <div><p className="font-medium">{r.toko}</p><p className="text-xs text-muted-foreground">{r.kode}</p></div>) },
          { kunci: 'target', label: 'Target (Rp)', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.target > 0 ? rpKolom(r.target) : '—'}</span> },
          { kunci: 'omzet', label: 'Omzet (Rp)', rata: 'kanan', isi: (r) => <span className="font-medium tabular-nums">{rpKolom(r.omzet)}</span> },
          { kunci: 'capaian', label: 'Capaian', rata: 'kanan', isi: (r) => {
            const s = STATUS_CAPAIAN[r.status] || STATUS_CAPAIAN.no_target;
            return (
              <div className="flex flex-col items-end gap-0.5">
                <span className="tabular-nums">{persen(r.capaian)}</span>
                <StatusBadge status={r.status} label={s.label} tone={s.tone} />
              </div>);
          } },
        ]} />
    </BagianGrafik>
  );
}

// ── Live selling ──────────────────────────────────────────────────────────────────────────────
export function BagianLive({ overview, onNavigate }) {
  const ov = overview.data;
  const galat = overview.galat ? pesanGagal(overview.galat.status, 'modul "Dashboard & Laporan Marketing"', overview.galat.detail) : '';
  const per = (ov?.per_account || [])
    .filter((a) => Number(a.revenue_live || 0) !== 0)
    .map((a) => ({ ...a, nama: a.account_name || a.account_code || '—' }))
    .sort((a, b) => Number(b.revenue_live) - Number(a.revenue_live));
  const sp = spec('batang_horizontal', per, [{ kunci: 'revenue_live', nama: 'Omzet live' }], { label: 'nama' });
  const sm = ov?.summary || {};
  const live = ov?.live || {};
  const buka = () => onNavigate?.('marketing-live-hub');
  const porsi = Number(sm.total_revenue || 0) > 0 ? (Number(sm.total_revenue_live || 0) / Number(sm.total_revenue) * 100) : null;
  return (
    <BagianGrafik testId="dash-live" judul="Live selling"
      keterangan="Omzet live resmi per toko = pesanan berkanal live (sama dengan kartu Omzet: termasuk live)."
      ringkasan={!overview.loading && !galat && ov && (Number(sm.total_revenue_live || 0) || Number(live.sessions || 0)) ? (
        <>Omzet live <b className="text-foreground">{fmtRp(sm.total_revenue_live)}</b>
          {porsi != null && Number(sm.total_revenue_live || 0) > 0 ? ` (${persen(porsi)} dari omzet)` : ''}
          {Number(live.orders || 0) > 0 ? ` dari ${angka(live.orders)} pesanan berkanal live` : ''} · {angka(live.sessions)} sesi live tercatat
          {Number(live.recorded_revenue || 0) > 0 ? ` (catatan sesi ${fmtRp(live.recorded_revenue)} — pembanding, bukan omzet resmi)` : ''}</>
      ) : null}
      tautan={<TautanSumber label="Live selling" onClick={buka} testId="dash-live-buka" />}>
      <KotakGrafik testId="dash-live-grafik" spesifikasi={sp} loading={overview.loading && !ov} galat={galat}
        kosong={<EmptyState icon={Radio} title="Belum ada omzet live pada periode ini"
          description={Number(live.sessions || 0) > 0
            ? `${angka(live.sessions)} sesi live tercatat, tetapi belum ada pesanan berkanal live dari impor pesanan.`
            : 'Omzet live terbaca dari pesanan berkanal live pada impor pesanan toko.'}
          action={<Button variant="outline" onClick={buka}>Buka live selling</Button>} />} />
    </BagianGrafik>
  );
}

// ── KOL / kreator ─────────────────────────────────────────────────────────────────────────────
export function BagianKreator({ token, info, tokoId, muatUlang, onNavigate }) {
  const [y, m] = String(info.bulan).split('-');
  const res = useAmbilJson(`${API}/api/marketing/targets/creator/monthly-summary?year=${Number(y)}&month=${Number(m)}`, token, muatUlang);
  const galat = galatDari(res, MODUL_ANGGARAN);
  const baris = galat ? [] : barisKreator(res.data?.creators, tokoId);
  const atas = baris.filter((r) => r.omzet > 0 || (r.target || 0) > 0).slice(0, 10);
  const sp = spec('batang_horizontal', atas, [{ kunci: 'target', nama: 'Target omzet' }, { kunci: 'omzet', nama: 'Omzet tercatat' }],
    { label: 'nama', catatan: baris.length > atas.length && atas.length === 10 ? `10 kreator teratas dari ${baris.length}.` : '' });
  const buka = () => onNavigate?.('marketing-targets');
  return (
    <BagianGrafik testId="dash-kreator" judul="KOL / kreator"
      keterangan={`Omzet tercatat dari sesi kreator vs target, bulan ${labelBulanMarketing(info.bulan)} — sama dengan Target & Anggaran › Target KOL.`}
      ringkasan={!res.loading && !galat && baris.length ? 'Omzet kreator = catatan sesi kreator (bukan omzet resmi toko); sebagian sudah termasuk di omzet toko.' : null}
      alat={(
        <TombolUnduh namaBerkas={`kreator-${info.bulan}`} namaLembar="KOL per kreator" baris={baris} testId="dash-kreator-unduh"
          kolom={[
            { label: 'Kreator', nilai: (r) => r.nama }, { label: 'Kode', nilai: (r) => r.kode }, { label: 'Toko', nilai: (r) => r.toko },
            { label: 'Omzet tercatat (Rp)', nilai: (r) => r.omzet }, { label: 'Target omzet (Rp)', nilai: (r) => (r.target == null ? '' : r.target) },
            { label: 'Capaian (%)', nilai: (r) => (r.capaian == null ? '' : r.capaian) }, { label: 'Sesi live', nilai: (r) => r.sesi },
          ]} />
      )}
      tautan={<TautanSumber label="Target KOL" onClick={buka} testId="dash-kreator-buka" />}>
      <KotakGrafik testId="dash-kreator-grafik" spesifikasi={sp} loading={res.loading} galat={galat} tombolAngka={false}
        kosong={<EmptyState icon={Users} title={`Belum ada omzet atau target kreator bulan ${namaBulan(info.bulan)}`}
          description="Sesi kreator dicatat di KOL & Kreator; targetnya di Target & Anggaran › Target KOL."
          action={<Button variant="outline" onClick={buka}>Buka target KOL</Button>} />} />
      <TabelData baris={res.loading ? [] : baris} kunci={(r) => r.id} testId="dash-kreator-tabel"
        kosong={<EmptyState icon={Users}
          title={galat ? 'Data kreator tidak bisa dimuat' : (res.loading ? 'Memuat kreator…' : (tokoId ? 'Tidak ada kreator di toko ini' : 'Belum ada kreator aktif'))}
          description={galat || undefined} />}
        kolom={[
          { kunci: 'nama', label: 'Kreator', hp: 'judul', isi: (r) => (
            <div><p className="font-medium">{r.nama}</p><p className="text-xs text-muted-foreground">{r.kode}</p></div>) },
          { kunci: 'toko', label: 'Toko', hp: 'keterangan', isi: (r) => r.toko || <span className="text-muted-foreground">Belum ditugaskan</span> },
          { kunci: 'omzet', label: 'Omzet tercatat', rata: 'kanan', isi: (r) => <span className="font-medium tabular-nums">{fmtRp(r.omzet)}</span> },
          { kunci: 'target', label: 'Target', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.target ? fmtRp(r.target) : '—'}</span> },
          { kunci: 'capaian', label: 'Capaian', rata: 'kanan', isi: (r) => <span className="tabular-nums">{persen(r.capaian)}</span> },
          { kunci: 'sesi', label: 'Sesi live', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.sesi)}</span> },
        ]} />
    </BagianGrafik>
  );
}

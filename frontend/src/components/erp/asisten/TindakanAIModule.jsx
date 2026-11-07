/**
 * Tindakan AI — Portal Management (Asisten AI Tahap B, Kontrak F, 8 Nov 2026; menu `asisten-ai-tindakan`).
 *
 * Riwayat perubahan data yang diusulkan Asisten AI dan keputusan atasnya (menunggu, dijalankan, dibatalkan, gagal,
 * kedaluwarsa, dibalikkan). Semua pengguna melihat tindakannya sendiri; owner/superadmin bisa menyalakan
 * "Semua pengguna". Rincian dibuka di bawah barisnya (RowDetail); "Balikkan" memulihkan nilai lama bila alatnya
 * mendukung (selalu lewat dialog konfirmasi).
 *
 *   GET  /api/asisten-ai/tindakan?status=&dari=&sampai=&halaman=&semua=1
 *   GET  /api/asisten-ai/tindakan/{id}
 *   POST /api/asisten-ai/tindakan/{id}/balikkan {alasan}
 *
 * PANDUAN_UI: PageLayout (penyaring status FilterChips + PeriodPicker di `filters`, muat ulang di `tools`),
 * tabel ui/table, rincian RowDetail, paginasi di `footer`.
 */
import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, ListChecks, MessageSquare, RefreshCw, Undo2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import FilterChips from '@/components/ui/filter-chips';
import { GlassCard } from '@/components/ui/glass';
import PaginationLite from '@/components/ui/pagination-lite';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateTimeID } from '@/lib/format';
import { parseServerTime } from '@/lib/waktu';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS, periodFromPreset } from '../finance/PeriodPicker';
import { KUNCI_SESI_AKTIF, asistenApi } from './asistenApi';
import { CatatanRencana, TabelPerubahan } from './KartuTindakan';
import {
  STATUS_PENYARING, bacaDaftarTindakan, bolehSemuaPengguna, keadaanTindakan, queryDaftar, ratakanNilai,
} from './tindakanAsisten';

const KOLOM = 7;
const WAKTU_RINCIAN = [
  ['dibuat', 'Dibuat'],
  ['diputuskan_pada', 'Diputuskan'],
  ['dijalankan_pada', 'Dijalankan'],
  ['selesai_pada', 'Selesai'],
  ['dibalikkan_pada', 'Dibalikkan'],
  ['kedaluwarsa_pada', 'Batas keputusan'],
];

const waktu = (v) => formatDateTimeID(parseServerTime(v));
// siapa yang memutuskan/membalikkan (inti: `diputuskan_oleh`/`dibalikkan_oleh` = {id, nama})
const OLEH = { diputuskan_pada: 'diputuskan_oleh', dibalikkan_pada: 'dibalikkan_oleh' };

/** Nilai sebelum/sesudah/hasil sebagai daftar label → nilai (kunci teknis disembunyikan, lihat `ratakanNilai`). */
function DaftarNilai({ judul, nilai, baris: barisLangsung, testId }) {
  const { baris, lebih } = barisLangsung ? { baris: barisLangsung, lebih: 0 } : ratakanNilai(nilai);
  return (
    <div className="min-w-0 space-y-1" data-testid={testId}>
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{judul}</p>
      {baris.length === 0 ? (
        <p className="text-sm text-muted-foreground">—</p>
      ) : (
        <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-x-3 gap-y-1 text-sm">
          {baris.map((b, i) => (
            <Fragment key={i}>
              <dt className="min-w-0 break-words text-muted-foreground">{b.label}</dt>
              <dd className="min-w-0 break-words tabular-nums text-foreground">{b.nilai}</dd>
            </Fragment>
          ))}
        </dl>
      )}
      {lebih > 0 && <p className="text-xs text-muted-foreground">… dan {lebih} isian lagi</p>}
    </div>
  );
}

function RincianTindakan({ row, rincian, bolehBuka, onBukaSesi }) {
  if (!rincian || rincian.memuat) {
    return (
      <div className="space-y-2" data-testid="tindakan-ai-rincian-memuat">
        <Skeleton className="h-5 w-1/3" /><Skeleton className="h-16 w-full" />
      </div>
    );
  }
  if (rincian.galat) return <Notice tone="danger" icon={AlertCircle} testId="tindakan-ai-rincian-galat">{rincian.galat}</Notice>;
  const d = rincian.data || {};
  const rencana = d.rencana && typeof d.rencana === 'object' ? d.rencana : {};
  const sumberWaktu = { dibuat: row.dibuat, ...(d.waktu && typeof d.waktu === 'object' ? d.waktu : {}), ...d };
  // batas keputusan hanya bermakna selagi menunggu (atau untuk menjelaskan kedaluwarsa)
  const pakaiBatas = ['menunggu', 'kedaluwarsa'].includes(row.keadaan);
  const daftarWaktu = WAKTU_RINCIAN.filter(([k]) => sumberWaktu[k] && (k !== 'kedaluwarsa_pada' || pakaiBatas))
    .map(([k, label]) => {
      const oleh = OLEH[k] && d[OLEH[k]]?.nama;
      return { label, nilai: oleh ? `${waktu(sumberWaktu[k])} · ${oleh}` : waktu(sumberWaktu[k]) };
    });
  const ringkasHasil = d.ringkas || row.ringkas;
  const sesiId = d.sesi_id || row.sesi_id;
  const bolehBukaSesi = typeof d.milik_sendiri === 'boolean' ? d.milik_sendiri : bolehBuka;
  const teksBaris = (t) => (t === null || t === undefined || t === '' ? '' : String(t));
  return (
    <div className="space-y-3 whitespace-normal" data-testid={`tindakan-ai-rincian-${row.id}`}>
      {rencana.ringkas && <p className="text-sm text-foreground/85">{String(rencana.ringkas)}</p>}
      <TabelPerubahan perubahan={rencana.perubahan} testId="tindakan-ai-perubahan" />
      <CatatanRencana rencana={rencana} />
      <div className="grid gap-4 lg:grid-cols-2">
        <DaftarNilai judul="Sebelum" nilai={d.sebelum} testId="tindakan-ai-sebelum" />
        <DaftarNilai judul="Sesudah" nilai={d.sesudah} testId="tindakan-ai-sesudah" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="min-w-0 space-y-1" data-testid="tindakan-ai-hasil">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Hasil</p>
          <p className="text-sm text-foreground">{ringkasHasil || '—'}</p>
          {teksBaris(d.pesan) && d.pesan !== ringkasHasil && <p className="text-sm text-muted-foreground">{teksBaris(d.pesan)}</p>}
          {teksBaris(d.alasan) && <p className="text-sm text-muted-foreground">Alasan persetujuan: {teksBaris(d.alasan)}</p>}
          {teksBaris(d.hasil_balik?.ringkas) && <p className="text-sm text-muted-foreground">Hasil pembalikan: {teksBaris(d.hasil_balik.ringkas)}</p>}
          {teksBaris(d.alasan_balik) && <p className="text-sm text-muted-foreground">Alasan dibalikkan: {teksBaris(d.alasan_balik)}</p>}
          {teksBaris(d.balik_gagal?.pesan) && (
            <p className="text-sm text-destructive" data-testid="tindakan-ai-balik-gagal">Pembalikan terakhir gagal: {teksBaris(d.balik_gagal.pesan)}</p>
          )}
          {ratakanNilai(d.hasil).baris.length > 0 && <DaftarNilai judul="Rincian hasil" nilai={d.hasil} testId="tindakan-ai-hasil-rinci" />}
        </div>
        {daftarWaktu.length > 0 && <DaftarNilai judul="Waktu" baris={daftarWaktu} testId="tindakan-ai-waktu" />}
      </div>
      {sesiId && bolehBukaSesi && (
        <Button variant="link" size="sm" className="h-auto px-0" onClick={() => onBukaSesi(sesiId)} data-testid="tindakan-ai-buka-sesi">
          <MessageSquare className="h-4 w-4" /> Buka percakapan asal
        </Button>
      )}
    </div>
  );
}

export default function TindakanAIModule({ user, onNavigate }) {
  const bolehSemua = bolehSemuaPengguna(user?.role);
  const [status, setStatus] = useState('');
  const [period, setPeriod] = useState(() => periodFromPreset('month'));
  const [semua, setSemua] = useState(false);
  const [halaman, setHalaman] = useState(1);
  const [data, setData] = useState(() => bacaDaftarTindakan([]));
  const [memuat, setMemuat] = useState(true);
  const [galat, setGalat] = useState('');
  const [bukaId, setBukaId] = useState(null);
  const [rincian, setRincian] = useState({});
  const [membalik, setMembalik] = useState(null);
  const urut = useRef(0);

  const muat = useCallback(async () => {
    const n = (urut.current += 1);
    setMemuat(true);
    setGalat('');
    try {
      const d = await asistenApi.daftarTindakan(queryDaftar({ status, period, halaman, semua: bolehSemua && semua }));
      if (n === urut.current) setData(bacaDaftarTindakan(d, halaman));
    } catch (e) {
      if (n === urut.current) setGalat(e?.message || 'Daftar tindakan gagal dimuat.');
    } finally {
      if (n === urut.current) setMemuat(false);
    }
  }, [status, period, halaman, semua, bolehSemua]);

  useEffect(() => { muat(); }, [muat]);

  const muatRincian = useCallback(async (id) => {
    setRincian((r) => ({ ...r, [id]: { memuat: true } }));
    try {
      const d = await asistenApi.detailTindakan(id);
      setRincian((r) => ({ ...r, [id]: { data: d || {} } }));
    } catch (e) {
      setRincian((r) => ({ ...r, [id]: { galat: e?.message || 'Rincian tindakan gagal dimuat.' } }));
    }
  }, []);

  const toggle = (id) => {
    if (bukaId === id) { setBukaId(null); return; }
    setBukaId(id);
    if (!rincian[id]?.data) muatRincian(id);
  };

  const saring = (fn) => (v) => { fn(v); setHalaman(1); setBukaId(null); };

  const bukaSesi = (sesiId) => {
    try { window.sessionStorage.setItem(KUNCI_SESI_AKTIF, sesiId); } catch { /* diblokir */ }
    onNavigate?.('asisten-ai');
  };

  const balikkan = async (row) => {
    if (membalik) return;
    const alasan = await confirmDialog({
      title: 'Balikkan tindakan ini?',
      body: `${row.judul || row.label || 'Tindakan AI'}. Nilai lama dipulihkan lewat jalur yang sama dengan layarnya; perubahan lain tidak ikut berubah.`,
      confirmLabel: 'Balikkan',
      cancelLabel: 'Kembali',
      input: { label: 'Alasan', minLength: 3, placeholder: 'Mis. target terlalu tinggi untuk bulan ini' },
    });
    if (!alasan) return;
    setMembalik(row.id);
    try {
      const r = await asistenApi.balikkanTindakan(row.id, alasan);
      toast.success(r?.ringkas || 'Tindakan dibalikkan; nilai lama dipulihkan.');
      setRincian((x) => { const n = { ...x }; delete n[row.id]; return n; });
      if (bukaId === row.id) muatRincian(row.id);
      await muat();
    } catch (e) {
      // 409 "Pembalikan gagal: …" → keadaan tetap dijalankan; rincian dimuat ulang supaya catatan gagalnya tampil
      toast.error(e?.message || 'Tindakan gagal dibalikkan.');
      if (bukaId === row.id) muatRincian(row.id);
    } finally {
      setMembalik(null);
    }
  };

  const { baris, total, perHalaman, jumlah } = data;
  const opsiStatus = [
    { key: '', label: 'Semua', count: jumlah ? STATUS_PENYARING.reduce((s, k) => s + (jumlah[k] || 0), 0) : undefined },
    ...STATUS_PENYARING.map((k) => ({ key: k, label: keadaanTindakan(k).label, count: jumlah ? jumlah[k] : undefined })),
  ];
  const disaring = !!status || period.preset !== 'all';
  const milikSendiri = (row) => !row.pengguna?.id || !user?.id || row.pengguna.id === user.id;

  return (
    <PageLayout
      testId="tindakan-ai-page"
      title="Tindakan AI"
      subtitle="Riwayat usulan perubahan dari Asisten AI: disetujui, dibatalkan, atau dibalikkan."
      filters={(
        <>
          <FilterChips options={opsiStatus} value={status} onChange={saring(setStatus)}
            ariaLabel="Penyaring keadaan" testId="tindakan-ai-status" />
          <PeriodPicker value={period} onChange={saring(setPeriod)} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId="tindakan-ai-periode" />
          {bolehSemua && (
            <label className="inline-flex h-9 items-center gap-2 text-sm text-foreground/80">
              <Switch checked={semua} onCheckedChange={saring(setSemua)} aria-label="Semua pengguna" data-testid="tindakan-ai-semua" />
              Semua pengguna
            </label>
          )}
        </>
      )}
      tools={(
        <Button variant="outline" size="icon" onClick={muat} title="Muat ulang" aria-label="Muat ulang" data-testid="tindakan-ai-muat-ulang">
          <RefreshCw className={memuat ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
        </Button>
      )}
      summary={galat ? <Notice tone="danger" icon={AlertCircle} testId="tindakan-ai-galat">{galat}</Notice> : null}
      footer={total > perHalaman ? (
        <PaginationLite page={halaman} totalPages={Math.ceil(total / perHalaman)} total={total} pageSize={perHalaman}
          onPageChange={(p) => { setHalaman(p); setBukaId(null); }} />
      ) : null}
    >
      <GlassCard className="overflow-hidden p-0" data-testid="tindakan-ai-kartu">
        {memuat && !baris.length ? (
          <div className="space-y-2 p-4" data-testid="tindakan-ai-memuat">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-9 w-full" />)}
          </div>
        ) : baris.length === 0 ? (
          <EmptyState icon={ListChecks} testId="tindakan-ai-kosong"
            title={disaring ? 'Tidak ada tindakan pada penyaring ini' : 'Belum ada tindakan AI'}
            description={disaring
              ? 'Ganti keadaan atau periode di atas untuk melihat tindakan lain.'
              : 'Usulan perubahan dari Asisten AI tampil di sini, lengkap dengan keputusan Anda dan tombol balikkan.'}
            action={!disaring && onNavigate ? { label: 'Buka Asisten AI', variant: 'outline', onClick: () => onNavigate('asisten-ai'), testId: 'tindakan-ai-ke-asisten' } : undefined} />
        ) : (
          <Table className="min-w-0 md:min-w-[860px]" data-testid="tindakan-ai-tabel">
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead className="hidden sm:table-cell">Waktu</TableHead>
                <TableHead className="hidden md:table-cell">Pengguna</TableHead>
                <TableHead>Tindakan</TableHead>
                <TableHead className="hidden md:table-cell">Ringkas</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Aksi</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {baris.map((row) => {
                const open = bukaId === row.id;
                const info = keadaanTindakan(row.keadaan);
                const sendiri = milikSendiri(row);
                return (
                  <Fragment key={row.id}>
                    <TableRow data-testid={`tindakan-ai-baris-${row.id}`} data-keadaan={row.keadaan}>
                      <TableCell><RowToggle open={open} onClick={() => toggle(row.id)} testId={`tindakan-ai-buka-${row.id}`} /></TableCell>
                      <TableCell className="hidden whitespace-nowrap text-xs text-muted-foreground sm:table-cell">{waktu(row.dibuat)}</TableCell>
                      <TableCell className="hidden text-sm md:table-cell">{row.pengguna?.nama || '—'}</TableCell>
                      <TableCell className="whitespace-normal sm:min-w-[9rem]">
                        <p className="text-sm font-medium text-foreground">{row.judul || row.label || 'Tindakan AI'}</p>
                        {row.judul && row.label && <p className="text-xs text-muted-foreground">{row.label}</p>}
                        {row.risiko === 'menengah' && <p className="text-xs text-muted-foreground">Risiko menengah</p>}
                        <p className="text-xs text-muted-foreground sm:hidden">{waktu(row.dibuat)}</p>
                      </TableCell>
                      <TableCell className="hidden max-w-[22rem] whitespace-normal text-sm text-foreground/80 md:table-cell">{row.ringkas || '—'}</TableCell>
                      <TableCell><StatusBadge status={row.keadaan} label={info.label} tone={info.tone} testId={`tindakan-ai-status-${row.id}`} /></TableCell>
                      <TableCell className="text-right">
                        {row.bisa_dibalikkan && row.keadaan === 'dijalankan' ? (
                          <Button size="sm" variant="outline" onClick={() => balikkan(row)} disabled={!!membalik}
                            title="Balikkan ke nilai lama" aria-label="Balikkan" data-testid={`tindakan-ai-balikkan-${row.id}`}>
                            <Undo2 className="h-4 w-4" /><span className="hidden sm:inline">Balikkan</span>
                          </Button>
                        ) : row.keadaan === 'menunggu' && sendiri && row.sesi_id ? (
                          <Button size="sm" variant="link" className="h-auto px-0" onClick={() => bukaSesi(row.sesi_id)}
                            title="Putuskan di percakapan asal" data-testid={`tindakan-ai-putuskan-${row.id}`}>
                            Putuskan
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                    {open && (
                      <RowDetail colSpan={KOLOM} testId={`tindakan-ai-detail-${row.id}`}>
                        <RincianTindakan row={row} rincian={rincian[row.id]} bolehBuka={sendiri} onBukaSesi={bukaSesi} />
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </GlassCard>
    </PageLayout>
  );
}

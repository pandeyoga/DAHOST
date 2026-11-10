/**
 * Monitoring Staf › Per staf — siapa memakai sistem dan seberapa patuh pada kewajibannya.
 * Kartu & tabel dari sumber yang sama (/api/pantau-staf/kartu dan /staf, satu perhitungan di backend).
 * Skor hanya untuk owner & admin (keputusan K3). Bulan pertama = uji coba tanpa sanksi (K6).
 */
import { useMemo, useState } from 'react';
import { ScanSearch } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PeriodPicker, { periodFromPreset } from '../finance/PeriodPicker';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import { RefreshButton, SearchBox } from '../pantau/pantauShared';
import { apiPost } from '../../../lib/api';
import { formatDateID } from '@/lib/format';
import StafDetailPopup from './StafDetailPopup';
import { NilaiBadge, namaPeran, persen, qs, useApi, waktu } from './pantauStafShared';

export const PRESET_PERIODE = [
  { key: 'month', label: 'Bulan ini' },
  { key: 'last_month', label: 'Bulan lalu' },
  { key: '3m', label: '3 bulan' },
  { key: 'custom', label: 'Pilih tanggal' },
];

const TIGA_HARI_MS = 3 * 24 * 3600 * 1000;

export function TombolPeriksa({ onSelesai }) {
  const [jalan, setJalan] = useState(false);
  const periksa = async () => {
    setJalan(true);
    try {
      const r = await apiPost('/pantau-staf/pindai', {});
      toast.success(r.galat?.length ? `Diperiksa ulang; ${r.galat.length} langkah gagal dibaca.` : 'Kewajiban diperiksa ulang dari data terbaru.');
      onSelesai?.();
    } catch (e) {
      toast.error(e.message || 'Gagal memeriksa ulang.');
    } finally {
      setJalan(false);
    }
  };
  return (
    <Button type="button" onClick={periksa} disabled={jalan} data-testid="pantau-staf-periksa"
      title="Baca ulang data semua langkah sekarang (otomatis tiap 15 menit)">
      <ScanSearch />{jalan ? 'Memeriksa…' : 'Periksa sekarang'}
    </Button>
  );
}

export default function PerStafTab({ onNavigate }) {
  const [periode, setPeriode] = useState(() => periodFromPreset('month'));
  const [cari, setCari] = useState('');
  const [saring, setSaring] = useState('');
  const [pilih, setPilih] = useState(null);
  const q = qs({ dari: periode.from, sampai: periode.to });
  const staf = useApi(`/pantau-staf/staf${q}`);
  const kartu = useApi(`/pantau-staf/kartu${q}`);
  const muat = () => { staf.reload(); kartu.reload(); };

  const items = useMemo(() => staf.data?.items || [], [staf.data]);
  const ujiCoba = !!staf.data?.masa_uji?.aktif;
  const tidakAktif = (r) => !r.aktif_terakhir || (Date.now() - new Date(r.aktif_terakhir).getTime()) > TIGA_HARI_MS;
  const opsi = [
    { key: '', label: 'Semua', count: items.length },
    { key: 'terlambat', label: 'Ada yang terlambat', count: items.filter((r) => r.terlambat > 0).length },
    { key: 'tidak_aktif', label: 'Jarang membuka sistem', count: items.filter(tidakAktif).length },
  ];
  const kata = cari.trim().toLowerCase();
  const baris = items
    .filter((r) => !saring || (saring === 'terlambat' ? r.terlambat > 0 : tidakAktif(r)))
    .filter((r) => !kata || `${r.nama} ${namaPeran(r.peran)}`.toLowerCase().includes(kata));
  const k = kartu.data || {};

  const kolom = [
    { kunci: 'nama', label: 'Staf', hp: 'judul', isi: (r) => (
      <div className="min-w-0">
        <p className="truncate font-medium">{r.nama}</p>
        <p className="truncate text-xs text-muted-foreground">{namaPeran(r.peran)}</p>
      </div>) },
    { kunci: 'aktif', label: 'Aktif terakhir', isi: (r) => (
      r.aktif_terakhir ? <span className="text-sm md:whitespace-nowrap">{waktu(r.aktif_terakhir)}</span> : (
        <div className="min-w-0">
          <p className="text-sm text-[hsl(var(--danger-text))]">Belum tercatat</p>
          <p className="text-xs text-muted-foreground">{r.login_terakhir ? `login terakhir ${formatDateID(r.login_terakhir)}` : 'belum pernah login'}</p>
        </div>)) },
    { kunci: 'hari', label: 'Hari aktif', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.hari_aktif} / {r.hari_kerja}</span> },
    { kunci: 'tepat', label: 'Tepat waktu', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.tepat} / {r.dinilai}</span> },
    { kunci: 'terlambat', label: 'Terlambat', rata: 'kanan', isi: (r) => (
      <span className={r.terlambat > 0 ? 'font-semibold tabular-nums text-[hsl(var(--danger-text))]' : 'tabular-nums'}>{r.terlambat}</span>) },
    { kunci: 'menunggu', label: 'Menunggu', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.menunggu}</span> },
    { kunci: 'kepatuhan', label: 'Kepatuhan', rata: 'kanan', isi: (r) => <span className="tabular-nums">{persen(r.kepatuhan)}</span> },
    { kunci: 'nilai', label: 'Nilai', isi: (r) => <NilaiBadge nilai={r.nilai} ujiCoba={ujiCoba} /> },
  ];

  return (
    <PageLayout testId="pantau-staf-per-staf" title="Per staf"
      subtitle="Siapa memakai sistem, dan berapa kewajibannya yang selesai tepat waktu."
      filters={<>
        <PeriodPicker value={periode} onChange={setPeriode} presets={PRESET_PERIODE} testId="pantau-staf-periode" />
        <SearchBox value={cari} onChange={setCari} placeholder="Cari nama atau peran" testId="pantau-staf-cari" />
        <FilterChips options={opsi} value={saring} onChange={setSaring} hideWhenEmpty={false} testId="pantau-staf-saring" />
      </>}
      actions={<TombolPeriksa onSelesai={muat} />}
      tools={<>
        <TombolUnduh namaBerkas={`monitoring-staf-${periode.from}-${periode.to}`} namaLembar="Per staf" baris={baris}
          testId="pantau-staf-unduh" kolom={[
            { label: 'Staf', nilai: (r) => r.nama }, { label: 'Peran', nilai: (r) => namaPeran(r.peran) },
            { label: 'Aktif terakhir', nilai: (r) => (r.aktif_terakhir ? waktu(r.aktif_terakhir) : 'Belum tercatat') },
            { label: 'Login terakhir', nilai: (r) => (r.login_terakhir ? waktu(r.login_terakhir) : 'Belum pernah') },
            { label: 'Hari aktif', nilai: (r) => r.hari_aktif }, { label: 'Hari kerja', nilai: (r) => r.hari_kerja },
            { label: 'Kewajiban dinilai', nilai: (r) => r.dinilai }, { label: 'Tepat waktu', nilai: (r) => r.tepat },
            { label: 'Dikerjakan orang lain', nilai: (r) => r.oleh_orang_lain },
            { label: 'Terlambat sekarang', nilai: (r) => r.terlambat }, { label: 'Menunggu', nilai: (r) => r.menunggu },
            { label: 'Kepatuhan (%)', nilai: (r) => (r.kepatuhan ?? '') },
            { label: 'Nilai', nilai: (r) => r.nilai?.huruf || '' },
          ]} />
        <RefreshButton onClick={muat} loading={staf.loading} testId="pantau-staf-muat" />
      </>}
      summary={<>
        {ujiCoba && (
          <Notice tone="info" title="Masa uji coba" testId="pantau-staf-uji-coba">
            Sampai {formatDateID(staf.data.masa_uji.sampai)} skor hanya untuk dipantau, belum dipakai untuk KPI atau sanksi.
          </Notice>
        )}
        {staf.error && <Notice tone="danger">{staf.error}</Notice>}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="pantau-staf-kartu">
          <StatTile label="Aktif hari ini" value={kartu.data ? `${k.aktif_hari_ini} / ${k.staf_total}` : '—'}
            hint="Akun staf (tanpa owner) yang membuka atau mengisi sistem hari ini" testId="kartu-aktif" />
          <StatTile label="Kewajiban terlambat" value={kartu.data ? k.terlambat_sekarang : '—'}
            accent={k.terlambat_sekarang > 0 ? 'danger' : 'default'}
            hint="Langkah yang batas waktunya sudah lewat dan belum ada buktinya di data" testId="kartu-terlambat" />
          <StatTile label="Tepat waktu" value={kartu.data ? persen(k.tepat_waktu) : '—'}
            sub={kartu.data ? `${k.dinilai} kewajiban jatuh tempo di periode ini` : ''}
            hint="Selesai sebelum batas oleh pemegangnya sendiri ÷ kewajiban yang sudah jatuh tempo" testId="kartu-tepat" />
          <StatTile label="Tidak aktif ≥ 3 hari kerja" value={kartu.data ? k.tidak_aktif_3_hari : '—'}
            accent={k.tidak_aktif_3_hari > 0 ? 'warning' : 'default'}
            hint="Aktivitas terakhir lebih dari 3 hari kerja lalu, atau belum pernah" testId="kartu-tidak-aktif" />
        </div>
      </>}>
      {staf.loading && !staf.data ? (
        <p className="py-4 text-center text-sm text-muted-foreground">Memuat…</p>
      ) : (
        <TabelData kolom={kolom} baris={baris} kunci={(r) => r.user_id} onKlikBaris={setPilih} testId="pantau-staf-tabel"
          kosong={<EmptyState title={items.length ? 'Tidak ada staf yang cocok' : 'Belum ada akun staf'}
            description={items.length ? 'Ubah saringan atau kata pencarian.' : 'Akun staf internal yang aktif akan tampil di sini.'} />} />
      )}
      {pilih && (
        <StafDetailPopup uid={pilih.user_id} nama={pilih.nama} periode={periode} ujiCoba={ujiCoba}
          onClose={() => setPilih(null)} onNavigate={onNavigate} />
      )}
    </PageLayout>
  );
}

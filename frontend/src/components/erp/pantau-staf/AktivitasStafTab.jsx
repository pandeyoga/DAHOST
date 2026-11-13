/**
 * Pemantauan staf › Aktivitas staf (14 Nov 2026) — apa yang dicatat tiap staf di sistem pada SATU hari, dalam
 * bahasa pekerjaan ("Impor pesanan marketplace 2× (217 baris pesanan)"), bukan nama menu atau jumlah klik.
 * Pekerjaan dibaca dari langkah alur yang sama dengan tab Alur kerja (satu sumber). Akun yang hanya membuka layar
 * atau tidak aktif sama sekali ikut tampil supaya terlihat siapa yang belum memakai sistem.
 * Klik baris → rinciannya di bawah baris itu (RowDetail). Sumber: GET /api/pantau-staf/aktivitas.
 */
import { useMemo, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import DatePicker from '@/components/ui/date-picker';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout, { RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { RefreshButton, SearchBox } from '../pantau/pantauShared';
import { hariIniWIB, jamWIB, namaPeran, qs, useApi } from './pantauStafShared';

export const KEADAAN_STAF = {
  bekerja: { label: 'Mencatat pekerjaan', tone: 'success' },
  hanya_membuka: { label: 'Hanya membuka sistem', tone: 'warning' },
  tidak_aktif: { label: 'Tidak aktif', tone: 'danger' },
};

function jamAktif(r) {
  if (!r.pertama) return '—';
  return `${jamWIB(r.pertama)}–${jamWIB(r.terakhir)}`;
}

function Ringkas({ r }) {
  if (r.keadaan === 'tidak_aktif') return <span className="text-sm text-muted-foreground">Tidak ada catatan sama sekali</span>;
  if (!r.pekerjaan.length) {
    const bagian = [r.masuk ? `masuk ${r.masuk} kali` : '', r.tanya_asisten ? `bertanya ke Asisten AI ${r.tanya_asisten} kali` : '']
      .filter(Boolean).join(', ');
    return <span className="text-sm text-muted-foreground">Tidak mencatat pekerjaan{bagian ? ` (${bagian})` : ''}</span>;
  }
  const atas = r.pekerjaan.slice(0, 3).map((p) => p.kalimat).join(' · ');
  return (
    <span className="text-sm">
      {atas}{r.pekerjaan.length > 3 ? <span className="text-muted-foreground"> · +{r.pekerjaan.length - 3} lainnya</span> : null}
    </span>
  );
}

function Rincian({ r, onNavigate }) {
  return (
    <div className="space-y-2" data-testid={`aktivitas-rincian-${r.user_id}`}>
      <p className="text-sm text-muted-foreground">
        Jam aktif {jamAktif(r)} · masuk sistem {r.masuk} kali · bertanya ke Asisten AI {r.tanya_asisten} kali
      </p>
      <TabelData baris={r.pekerjaan} kunci={(p) => `${p.alur}-${p.langkah}-${p.batal ? 'b' : 'k'}`}
        testId={`aktivitas-pekerjaan-${r.user_id}`}
        kosong={<EmptyState title="Tidak ada pekerjaan yang tercatat hari itu"
          description="Layar yang dibuka tanpa menyimpan apa pun tidak dihitung sebagai pekerjaan." />}
        kolom={[
          { kunci: 'alur', label: 'Alur', isi: (p) => <span className="text-sm text-muted-foreground">{p.alur}</span> },
          { kunci: 'kalimat', label: 'Pekerjaan', hp: 'judul', isi: (p) => (
            <p className={`whitespace-normal text-sm md:max-w-[32rem] ${p.batal ? 'text-[hsl(var(--danger-text))]' : ''}`}>{p.kalimat}</p>) },
          { kunci: 'buka', label: '', rata: 'kanan', hp: 'aksi', isi: (p) => p.link_module && (
            <Button size="sm" variant="link" onClick={() => onNavigate?.(p.link_module)}><ExternalLink />Buka</Button>) },
        ]} />
    </div>
  );
}

export default function AktivitasStafTab({ onNavigate }) {
  const [tanggal, setTanggal] = useState(hariIniWIB);
  const [cari, setCari] = useState('');
  const [saring, setSaring] = useState('');
  const [buka, setBuka] = useState('');
  const { data, loading, error, reload } = useApi(`/pantau-staf/aktivitas${qs({ tanggal })}`);
  const items = useMemo(() => data?.items || [], [data]);
  const r = data?.ringkasan || {};
  const opsi = [
    { key: '', label: 'Semua', count: items.length },
    ...Object.entries(KEADAAN_STAF).map(([key, v]) => ({ key, label: v.label, count: items.filter((x) => x.keadaan === key).length })),
  ];
  const kata = cari.trim().toLowerCase();
  const baris = items
    .filter((x) => !saring || x.keadaan === saring)
    .filter((x) => !kata || `${x.nama} ${namaPeran(x.peran)}`.toLowerCase().includes(kata));

  const kolom = [
    { kunci: 'nama', label: 'Staf', hp: 'judul', isi: (x) => (
      <div className="flex min-w-0 items-start gap-1.5">
        <span className="-ml-1 hidden md:block">
          <RowToggle open={buka === x.user_id} onClick={(e) => { e.stopPropagation(); setBuka(buka === x.user_id ? '' : x.user_id); }}
            label={`Lihat pekerjaan ${x.nama}`} testId={`aktivitas-toggle-${x.user_id}`} />
        </span>
        <div className="min-w-0">
          <p className="truncate font-medium">{x.nama}</p>
          <p className="truncate text-xs text-muted-foreground">{namaPeran(x.peran)}</p>
        </div>
      </div>) },
    { kunci: 'jam', label: 'Jam aktif', isi: (x) => <span className="tabular-nums text-sm md:whitespace-nowrap">{jamAktif(x)}</span> },
    { kunci: 'kerja', label: 'Yang dikerjakan', isi: (x) => <div className="whitespace-normal md:max-w-[30rem]"><Ringkas r={x} /></div> },
    { kunci: 'jumlah', label: 'Pekerjaan', rata: 'kanan', isi: (x) => <span className="tabular-nums">{x.jumlah_pekerjaan}</span> },
    { kunci: 'keadaan', label: 'Keadaan', isi: (x) => {
      const k = KEADAAN_STAF[x.keadaan] || KEADAAN_STAF.tidak_aktif;
      return <StatusBadge status={x.keadaan} label={k.label} tone={k.tone} />;
    } },
  ];

  return (
    <PageLayout testId="pantau-staf-aktivitas" title="Aktivitas staf"
      subtitle="Apa yang dicatat tiap staf di sistem pada hari itu, ditulis sebagai pekerjaan."
      filters={<>
        <div className="w-full sm:w-44">
          <DatePicker value={tanggal} onChange={(v) => v && setTanggal(v)} max={hariIniWIB()} bolehKosong={false}
            testId="aktivitas-tanggal" />
        </div>
        <SearchBox value={cari} onChange={setCari} placeholder="Cari nama atau peran" testId="aktivitas-cari" />
        <FilterChips options={opsi} value={saring} onChange={setSaring} hideWhenEmpty={false} testId="aktivitas-saring" />
      </>}
      tools={<>
        <TombolUnduh namaBerkas={`aktivitas-staf-${tanggal}`} namaLembar="Aktivitas staf" baris={baris} testId="aktivitas-unduh"
          kolom={[
            { label: 'Staf', nilai: (x) => x.nama }, { label: 'Peran', nilai: (x) => namaPeran(x.peran) },
            { label: 'Jam aktif', nilai: (x) => jamAktif(x) },
            { label: 'Keadaan', nilai: (x) => (KEADAAN_STAF[x.keadaan] || {}).label || '' },
            { label: 'Jumlah pekerjaan', nilai: (x) => x.jumlah_pekerjaan },
            { label: 'Yang dikerjakan', nilai: (x) => x.pekerjaan.map((p) => p.kalimat).join('; ') },
            { label: 'Masuk sistem', nilai: (x) => x.masuk }, { label: 'Tanya Asisten AI', nilai: (x) => x.tanya_asisten },
          ]} />
        <RefreshButton onClick={reload} loading={loading} testId="aktivitas-muat" />
      </>}
      summary={<>
        {error && <Notice tone="danger">{error}</Notice>}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3" data-testid="aktivitas-kartu">
          <StatTile label="Mencatat pekerjaan" value={data ? `${r.bekerja} / ${r.staf}` : '—'} testId="aktivitas-kartu-bekerja"
            hint="Staf (tanpa owner) yang mengerjakan minimal satu langkah alur di sistem pada tanggal ini" />
          <StatTile label="Hanya membuka sistem" value={data ? r.hanya_membuka : '—'} testId="aktivitas-kartu-membuka"
            accent={r.hanya_membuka > 0 ? 'warning' : 'default'}
            hint="Masuk, membuka layar, atau bertanya ke Asisten AI, tetapi tidak menyimpan pekerjaan apa pun" />
          <StatTile label="Tidak aktif" value={data ? r.tidak_aktif : '—'} testId="aktivitas-kartu-tidak-aktif"
            accent={r.tidak_aktif > 0 ? 'danger' : 'default'}
            hint="Tidak ada catatan sama sekali pada tanggal ini (tidak masuk, tidak membuka layar)" />
        </div>
      </>}>
      {loading && !data ? <p className="py-4 text-center text-sm text-muted-foreground">Memuat…</p> : (
        <TabelData kolom={kolom} baris={baris} kunci={(x) => x.user_id} testId="aktivitas-tabel"
          onKlikBaris={(x) => setBuka(buka === x.user_id ? '' : x.user_id)}
          rincian={(x) => (buka === x.user_id ? <Rincian r={x} onNavigate={onNavigate} /> : null)}
          kosong={<EmptyState title={items.length ? 'Tidak ada staf yang cocok' : 'Belum ada akun staf'}
            description={items.length ? 'Ubah saringan atau kata pencarian.' : 'Akun staf internal yang aktif akan tampil di sini.'} />} />
      )}
    </PageLayout>
  );
}
